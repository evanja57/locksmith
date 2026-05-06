# -*- encoding: utf-8 -*-
"""
Handlers for turret.

Classes:
    - UnlockHandler: Handles the `/unlock` resource for processing peer-to-peer challenge response messages.
    - CheckLockHandler: Handles the `/checklock` resource to check the lock state of the credentials.
    - PopupClosureHandler: Handles the `/closure` resource to start a timer when a popup is closed.
    - IdentifiersHandler: Handles the `/identifiers` resource for managing identifier-related requests.
    - SignHandler: Handles the `/sign` resource for signing data based on provided information.
    - VerifyHandler: Handles the `/verify` resource to verify data signed by the turret.
    - KELHandler: Handles the `/kel` resource for retrieving the Key Event Log (KEL) of a specified identifier.
    - OOBIHandler: Handles the `/oobi` resource for resolving Out-Of-Band Introductions (OOBIs).
    - DecryptHandler: Handles the `/decrypt` resource for decrypting data using a designated decryption key.
"""
import json
import random
import traceback
from urllib.parse import urljoin

import falcon
from hio import help
from hio.base import doing
from hio.help import decking, Hict
from keri import kering
from keri.app.httping import CESR_DESTINATION_HEADER
from keri.core import coring
from keri.db import basing
from keri.help import helping
from locksmith.core import ipexing
from locksmith.turret.authing import Authenticator

logger = help.ogler.getLogger()


class IdentifiersHandler:
    """  Handle challenge response peer to peer `exn` message """

    resource = "/identifiers"

    def __init__(self, hby, cues):
        """ Initialize peer to peer challenge response messsage """
        self.hby = hby
        self.cues = cues

        super(IdentifiersHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event

        """

        try:
            identifiers = []
            for (ns, alias), prefix in self.hby.db.names.getTopItemIter(keys=()):
                if ns != "":
                    continue
                msg = dict(name=alias, prefix=prefix)
                identifiers.append(msg)

            self.cues.append(dict(status=falcon.HTTP_200, body=identifiers))
        except (kering.AuthError, ValueError) as e:
            msg = dict(status=falcon.HTTP_400, body=str(e))
            self.cues.append(msg)


class CredentialsHandler:
    """  Handle challenge response peer to peer `exn` message """

    resource = "/credentials"

    def __init__(self, hby, rgy, cues):
        """ Initialize peer to peer challenge response messsage """
        self.hby = hby
        self.rgy = rgy
        self.cues = cues

        super(CredentialsHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event

        """

        try:
            saids = list()
            credentials = list()
            for pre in self.hby.habs.keys():
                saids.extend([saider for saider in self.rgy.reger.subjs.get(keys=(pre,))])
            creds = self.rgy.reger.cloneCreds(saids, self.hby.db)

            for credential in creds:
                sad = credential['sad']
                attribs = sad['a']
                schemer = credential.get("schema")
                status = credential.get("status", {})

                holder_hab = self.hby.habByPre(attribs['i'])

                if status['et'] == 'iss' or status['et'] == 'bis':
                    status_text = "Received / Active"
                elif status['et'] == 'rev' or status['et'] == 'brv':
                    status_text = "Received / Revoked"
                else:
                    status_text = "Not Received"

                dt = helping.fromIso8601(status['dt'])

                cred_dict = {
                    "schema_title": schemer.get("title", ""),
                    "schema_said": schemer.get("$id", ""),
                    "holder_pre": holder_hab.pre,
                    "holder_name": f"{holder_hab.name} ({holder_hab.pre})" if holder_hab else "Unknown",  # Issuer is the 'i' field
                    "status": status_text,
                    "received_date": dt.strftime("%b %d, %Y %I:%M %p"),
                    "said": sad['d']  # Store SAID for view operation
                }

                credentials.append(cred_dict)


            self.cues.append(dict(status=falcon.HTTP_200, body=credentials))
        except (kering.AuthError, ValueError) as e:
            msg = dict(status=falcon.HTTP_400, body=str(e))
            self.cues.append(msg)


class IPEXGrantRequestHandler:
    """  Handle challenge response peer to peer `exn` message """

    resource = "/ipex/grant/request"

    def __init__(self, hby, rgy, cues):
        """ Initialize peer to peer challenge response messsage """
        self.hby = hby
        self.rgy = rgy
        self.cues = cues

        super(IPEXGrantRequestHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event

        """

        try:
            payload = serder.ked.get("a", {})
            grantor = payload["grantor"]
            recipient = payload["recipient"]
            credential_said = payload["credential_said"]
            message = payload.get("message", "")

            hab = self.hby.habByPre(grantor)
            if not hab:
                msg = dict(status=falcon.HTTP_400, body=f"Invalid grantor: {grantor}")
                self.cues.append(msg)
                return

            granter = ipexing.Granter(
                self.hby,
                hab,
                self.rgy
            )
            grant = granter.grant(
                credential_said,
                recp=recipient,
                message=message
            )
            self.cues.append(dict(status=falcon.HTTP_200, body=grant.decode("utf-8")))

        except (kering.AuthError, ValueError) as e:
            msg = dict(status=falcon.HTTP_400, body=str(e))
            self.cues.append(msg)



class SignHandler:
    resource = "/sign"

    def __init__(self, cues, base, cred):
        """ Initialize peer to peer challenge response messsage """

        self.cues = cues
        self.base = base
        self.cred = cred
        super(SignHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event
        """
        payload = serder.ked['a']
        method = payload["method"] if "method" in payload else None
        # data = payload["data"] if "data" in payload else None
        path = payload["path"] if "path" in payload else None
        signator = payload["signator"] if "signator" in payload else None
        DefaultFields = ["Signify-Resource",
                         "@method",
                         "@path",
                         "Signify-Timestamp"]

        if self.cred.hby is not None:
            try:
                auth = Authenticator(hby=self.cred.hby, method=method, path=path, signator=signator,
                                     defaultFields=DefaultFields)
                headers = auth.sign()
                self.cues.append(dict(status=falcon.HTTP_200, body=dict(headers)))
            except (kering.AuthError, ValueError) as e:
                print(traceback.format_exc())
                msg = dict(status=falcon.HTTP_400, body=str(e))
                self.cues.append(msg)
            except Exception as e:
                print(traceback.format_exc())
                msg = dict(status=falcon.HTTP_400, body=str(e))
                self.cues.append(msg)
        else:
            msg = dict(status=falcon.HTTP_200, body=False)
            self.cues.append(msg)


class VerifyHandler:
    resource = "/verify"

    def __init__(self, cues, base, cred):
        """ Initialize peer to peer challenge response messsage """

        self.cues = cues
        self.base = base
        self.cred = cred
        super(VerifyHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event
        """
        payload = serder.ked['a']
        headers = payload["headers"] if "headers" in payload else None
        root = payload["root"] if "root" in payload else None
        headers = {header['name'].lower(): header['value'] for header in headers}
        if self.cred.hby is not None:
            try:
                auth = Authenticator(hby=self.cred.hby, method=None, path=None, root=root,
                                     defaultFields=None)
                verified = auth.verify(headers=headers)
                if verified:
                    self.cred.startTimer()
                self.cues.append(dict(status=falcon.HTTP_200, body=verified))

            except Exception as e:
                msg = dict(status=falcon.HTTP_200, body=False)
                self.cues.append(msg)
                print(e)

        else:
            msg = dict(status=falcon.HTTP_200, body=False)
            self.cues.append(msg)
            return


class KELHandler:
    resource = "/kel"

    def __init__(self, cues, base, cred):
        """ Initialize peer to peer challenge response messsage """

        self.cues = cues
        self.base = base
        self.cred = cred
        super(KELHandler, self).__init__()

    def handle(self, serder, attachments=None):
        payload = serder.ked['a']
        signator = payload["signator"] if "signator" in payload else None
        prefix = payload["prefix"] if "prefix" in payload else None
        role = payload["role"] if "role" in payload else "witness"

        if self.cred.hby is not None:

            hab = None
            if prefix is not None:
                hab = self.cred.hby.habByPre(prefix)
            elif signator is not None:
                hab = self.cred.hby.habByName(signator)

            if hab is None:
                msg = dict(status=falcon.HTTP_400, body=f"neither signator {signator} nor prefix {prefix} are correct")
                self.cues.append(msg)
                return

            oobi = ""
            try:
                if role in (kering.Roles.witness,):
                    if not hab.kever.wits:
                        raise ValueError(f"{hab.name} identifier {hab.pre} does not have any witnesses.")

                    wit = random.choice(hab.kever.wits)
                    urls = hab.fetchUrls(eid=wit, scheme=kering.Schemes.http) \
                           or hab.fetchUrls(eid=wit, scheme=kering.Schemes.https)

                    if not urls:
                        raise kering.ConfigurationError(f"unable to query witness {wit}, no http endpoint")

                    url = urls[kering.Schemes.https] if kering.Schemes.https in urls else urls[kering.Schemes.http]
                    oobi = f"{url.rstrip("/")}/oobi/{hab.pre}/witness"

                elif role in (kering.Roles.controller,):
                    urls = hab.fetchUrls(eid=hab.pre, scheme=kering.Schemes.http) \
                           or hab.fetchUrls(eid=hab.pre, scheme=kering.Schemes.https)
                    if not urls:
                        raise ValueError(f"{hab.name} identifier {hab.pre} does not have any controller endpoints")

                    url = urls[kering.Schemes.https] if kering.Schemes.https in urls else urls[kering.Schemes.http]
                    oobi = f"{url.rstrip("/")}/oobi/{hab.pre}/controller"
                elif role in (kering.Roles.mailbox,):
                    for (_, _, eid), end in hab.db.ends.getTopItemIter(keys=(hab.pre, kering.Roles.mailbox,)):
                        if not (end.allowed and end.enabled is not False):
                            continue

                        urls = hab.fetchUrls(eid=eid, scheme=kering.Schemes.http) or hab.fetchUrls(eid=hab.pre,
                                                                                                   scheme=kering.Schemes.https)
                        if not urls:
                            raise ValueError(f"{hab.name} identifier {hab.pre} does not have any mailbox endpoints")

                        url = urls[kering.Schemes.https] if kering.Schemes.https in urls else urls[kering.Schemes.http]
                        oobi = f"{url.rstrip("/")}/oobi/{hab.pre}/mailbox/{eid}"
                else:
                    raise ValueError(f"{role} is not a value OOBI role")

            except:
                oobi = ""

            try:
                kel = bytearray()
                for msg in hab.db.clonePreIter(pre=hab.pre):
                    kel.extend(msg)

                kel.extend(hab.replyToOobi(aid=hab.pre, role="controller"))
                kel = bytes(kel).decode("utf-8")

                self.cues.append(dict(status=falcon.HTTP_200, body=dict(kel=kel, oobi=oobi)))
            except Exception as e:
                msg = dict(status=falcon.HTTP_400, body=str(e))
                self.cues.append(msg)


class OOBIHandler(doing.Doer):
    """  Handle challenge response peer to peer `exn` message """

    resource = "/oobi"

    def __init__(self, cues, base, cred):
        """ Initialize peer to peer challenge response messsage """

        self.msgs = decking.Deck()
        self.cues = cues
        self.base = base
        self.cred = cred

        super(OOBIHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event

        """
        self.msgs.append((serder, attachments))

    def recur(self, tyme=None):
        while True:
            if self.msgs:
                (serder, attachments) = self.msgs.pull()

                payload = serder.ked['a']
                oobi = payload["oobi"]
                oobiAlias = payload["oobiAlias"] if "oobiAlias" in payload else None
                force = payload["force"] if "force" in payload else False
                try:
                    if force:  # if force specified, remove previous record of OOBI resolution
                        self.cred.hby.db.roobi.rem(keys=(oobi,))

                    obr = basing.OobiRecord(date=helping.nowIso8601())
                    if oobiAlias is not None:
                        obr.oobialias = oobiAlias

                    self.cred.hby.db.oobis.put(keys=(oobi,), val=obr)

                    while not self.cred.hby.db.roobi.get(keys=(oobi,)):
                        yield 0.25

                    obr = self.cred.hby.db.roobi.get(keys=(oobi,))
                    if force:
                        while obr.cid not in self.cred.hby.kevers:
                            self.cred.hby.kvy.processEscrows()
                            yield 0.25

                    msg = dict(status=falcon.HTTP_200, body={})

                except Exception as e:
                    msg = dict(status=falcon.HTTP_400, body=str(e))
                self.cues.append(msg)

            yield self.tock


class DecryptHandler:
    resource = "/decrypt"

    def __init__(self, cues, base, cred):
        """ Initialize peer to peer challenge response messsage """

        self.cues = cues
        self.base = base
        self.cred = cred
        super(DecryptHandler, self).__init__()

    def handle(self, serder, attachments=None):
        payload = serder.ked['a']
        decrypter = payload["decrypter"]
        data = payload["data"]

        if self.cred.hby is not None:
            try:
                hab = self.cred.hby.habByName(decrypter)
                totp = data["totp"]
                m = coring.Matter(qb64=totp)
                decryption = hab.decrypt(ser=m.raw)
                self.cues.append(dict(status=falcon.HTTP_200, body=decryption))
            except (kering.AuthError, ValueError) as e:
                msg = dict(status=falcon.HTTP_400, body=str(e))
                self.cues.append(msg)


class WitnessAuthHandler(doing.Doer):
    """  Handle challenge response peer to peer `exn` message """

    resource = "/witness/authenticate"

    def __init__(self, cues, base, cred, clienter):
        """ Initialize peer to peer challenge response messsage """

        self.msgs = decking.Deck()
        self.cues = cues
        self.base = base
        self.cred = cred
        self.clienter = clienter

        super(WitnessAuthHandler, self).__init__()

    def handle(self, serder, attachments=None):
        """  Do route specific processsing of Challenge response messages

        Parameters:
            serder (Serder): Serder of the exn challenge response message
            attachments (list): list of tuples of pather, CESR SAD path attachments to the exn event

        """
        self.msgs.append((serder, attachments))

    def recur(self, tyme=None):
        while True:
            if self.msgs:
                (serder, attachments) = self.msgs.pull()
                payload = serder.ked['a']

                oobi = payload["oobi"]
                alias = payload['name']
                obr = basing.OobiRecord(date=helping.nowIso8601(), oobialias=alias, )
                self.cred.hby.db.oobis.put(keys=(oobi,), val=obr)

                while not self.cred.hby.db.roobi.get(keys=(oobi,)):
                    yield 0.25

                eid = payload["eid"]
                cid = payload["cid"]
                hab = self.cred.hby.habs[cid]

                body = bytearray()
                for msg in self.cred.hby.db.clonePreIter(pre=hab.pre):
                    body.extend(msg)

                fargs = dict([("kel", body.decode("utf-8"))])

                if hab.kever.delegated:
                    delkel = bytearray()
                    for msg in hab.db.clonePreIter(hab.kever.delpre):
                        delkel.extend(msg)

                    fargs['delkel'] = delkel.decode("utf-8")

                headers = (Hict([
                    ("Content-Type", "multipart/form-data"),
                    (CESR_DESTINATION_HEADER, eid)
                ]))

                urls = hab.fetchUrls(eid=eid, scheme=kering.Schemes.http) or hab.fetchUrls(eid=eid,
                                                                                           scheme=kering.Schemes.https)
                if not urls:
                    msg = dict(status=falcon.HTTP_400, body=f"unable to query witness {eid}, no http endpoint")
                    self.cues.append(msg)
                    continue

                base = urls[kering.Schemes.http] if kering.Schemes.http in urls else urls[kering.Schemes.https]

                url = urljoin(base, f"/aids")
                client = self.clienter.request("POST", url, headers=headers, fargs=fargs)
                while not client.responses:
                    yield self.tock

                rep = client.respond()
                if rep.status == 200:
                    data = json.loads(rep.body)

                    totp = data["totp"]
                    m = coring.Matter(qb64=totp)  # refactor this to use cipher
                    d = coring.Matter(qb64=hab.decrypt(ser=m.raw))
                    otpurl = f"otpauth://totp/KERIpy:{eid}?secret={d.raw.decode('utf-8')}&issuer=KERIpy"

                    body = dict(otpurl=otpurl,
                                secret=d.raw.decode('utf-8'))
                    self.cues.append(dict(status=falcon.HTTP_200, body=body))
                else:
                    msg = dict(status=rep.status, body=rep.body.decode("utf-8"))
                    self.cues.append(msg)

                self.clienter.remove(client)

            yield self.tock
