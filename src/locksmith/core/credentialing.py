# -*- encoding: utf-8 -*-
"""
locksmith.core.credentialing module

Doers for credential-related operations including schema management and credential issuance.
"""
import requests
from hio.base import doing
from keri import help, core, kering
from keri.app import grouping, forwarding, signing, habbing, agenting
from keri.app.habbing import GroupHab
from keri.core import scheming, coring, serdering, eventing, signing as core_signing
from keri.core.eventing import SealEvent
from keri.db.dbing import dgKey
from keri.help import helping
from keri.kering import Kinds
from keri.vdr import credentialing, verifying

logger = help.ogler.getLogger(__name__)


class LoadSchemaDoer(doing.DoDoer):
    """Doer for asynchronous schema loading and registry creation."""

    def __init__(self, app, oobi=None, file_path=None, file_content=None, create_registry=False, issuer_aid=None,
                 auth_codes=None, signal_bridge=None):
        """
        Initialize the LoadSchemaDoer.

        Args:
            app: Application instance
            oobi: OOBI URL to load schema from (mutually exclusive with file_path/file_content)
            file_path: Path to schema file (mutually exclusive with oobi)
            file_content: Raw schema content as bytes (used with file_path for logging)
            create_registry: Whether to create a credential registry for this schema
            issuer_aid: AID of the identifier to use as the registry issuer (required if create_registry is True)
            auth_codes: Optional list of "witness_id:passcode" strings for witness authentication
            signal_bridge: DoerSignalBridge instance for emitting Qt signals
        """
        self.app = app
        self.hby = self.app.vault.hby
        self.rgy = self.app.vault.rgy
        self.oobi = oobi
        self.file_path = file_path
        self.file_content = file_content
        self.create_registry = create_registry
        self.issuer_aid = issuer_aid
        self.auth_codes = auth_codes
        self.signal_bridge = signal_bridge

        # Validate inputs
        if not oobi and not file_content:
            raise ValueError("Either oobi or file_content must be provided")
        if oobi and file_content:
            raise ValueError("Only one of oobi or file_content can be provided")

        # Create generator-based doer
        doers = [doing.doify(self.load_schema_do)]
        super(LoadSchemaDoer, self).__init__(doers=doers)

    def load_schema_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for schema loading and registry creation.

        Args:
            tymth: Time function
            tock: Tick interval
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Load schema based on source
            if self.oobi:
                schemer = self._load_from_oobi()
            else:
                schemer = self._load_from_content()

            title = schemer.sed.get('title', 'Untitled')
            # Store the schema in the database
            self.hby.db.schema.pin(keys=(schemer.said,), val=schemer)
            logger.info(f"Schema stored in database: {title} ({schemer.said})")

            # Create credential registry if requested
            registry_name = None
            if self.create_registry:
                registry_name = yield from self._create_registry(schemer.said, title)
                logger.info(f"Created credential registry: {registry_name}")

            # Emit success signal
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="LoadSchemaDoer",
                    event_type="schema_loaded",
                    data={
                        'title': title,
                        'said': schemer.said,
                        'registry_name': registry_name,
                        'create_registry': self.create_registry,
                        'success': True
                    }
                )

            logger.info(f"Schema loading complete: {title}")
            return

        except Exception as e:
            logger.exception(f"LoadSchemaDoer failed: {e}")

            # Emit failure signal
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="LoadSchemaDoer",
                    event_type="schema_load_failed",
                    data={
                        'error': str(e),
                        'oobi': self.oobi,
                        'file_path': self.file_path,
                        'success': False
                    }
                )
            return

    def _load_from_oobi(self):
        """
        Load schema from OOBI URL.

        Returns:
            Schemer: The loaded schema
        """
        logger.info(f"Fetching schema from OOBI: {self.oobi}")

        response = requests.get(self.oobi, allow_redirects=True)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch OOBI: HTTP {response.status_code}")

        schemer = scheming.Schemer(raw=response.content)
        logger.info(f"Schema fetched from OOBI: {schemer.sed.get('title', 'Untitled')}")

        return schemer

    def _load_from_content(self):
        """
        Load schema from file content.

        Returns:
            Schemer: The loaded schema
        """
        logger.info(f"Loading schema from file content: {self.file_path}")

        schemer = scheming.Schemer(raw=self.file_content)
        logger.info(f"Schema loaded from file: {schemer.sed.get('title', 'Untitled')}")

        return schemer

    def _create_registry(self, schema_said, schema_title):
        """
        Create a credential registry for the schema.

        Args:
            schema_said: SAID of the schema

        Returns:
            str: Name of the created registry
        """
        # Use schema SAID as registry name
        counselor = grouping.Counselor(hby=self.hby)

        # Convert auth_codes list to dict format if provided
        auths = {}
        if self.auth_codes:
            code_time = helping.nowIso8601()
            for arg in self.auth_codes:
                wit, code = arg.split(":")
                auths[wit] = f"{code}#{code_time}"

        registrar = Registrar(hby=self.hby, rgy=self.rgy, counselor=counselor, auth=auths)
        postman = forwarding.Poster(hby=self.hby)

        self.extend([counselor, registrar, postman])

        registry_name = schema_said

        # Check if registry already exists
        if registry_name in self.rgy.regs:
            logger.info(f"Registry already exists: {registry_name}")
            return registry_name

        # Validate that issuer AID was provided
        if not self.issuer_aid:
            raise Exception("Issuer AID is required for registry creation")

        # Get the hab for the issuer AID
        if self.issuer_aid not in self.hby.habs:
            raise Exception(f"Issuer identifier {self.issuer_aid} not found")

        hab = self.hby.habs[self.issuer_aid]

        logger.info(f"Creating credential registry: {registry_name} for issuer {hab.name} ({hab.pre})")

        kwa = dict(nonce=core_signing.Salter().qb64)
        registry = self.rgy.makeRegistry(name=registry_name, prefix=hab.pre, **kwa)

        rseal = SealEvent(registry.regk, "0", registry.regd)
        rseal = dict(i=rseal.i, s=rseal.s, d=rseal.d)

        anc = hab.interact(data=[rseal])

        aserder = serdering.SerderKERI(raw=bytes(anc))
        registrar.incept(iserder=registry.vcp, anc=aserder)

        if isinstance(hab, GroupHab):
            smids = hab.db.signingMembers(pre=hab.pre)
            smids.remove(hab.mhab.pre)

            for recp in smids:  # this goes to other participants only as a signaling mechanism
                exn, atc = grouping.multisigRegistryInceptExn(ghab=hab, vcp=registry.vcp.raw, anc=anc,
                                                              usage=f"Registry for schema {schema_title}")
                postman.send(src=hab.mhab.pre,
                             dest=recp,
                             topic="multisig",
                             serder=exn,
                             attachment=atc)

        while not registrar.complete(pre=registry.regk, sn=0):
            self.rgy.processEscrows()
            yield self.tock

        logger.info(f"Registry {registry_name}({registry.regk}) created for Identifier Prefix: {hab.pre}")

        self.remove([counselor, registrar, postman])

        return registry_name


class IssueCredentialDoer(doing.DoDoer):
    """Doer for asynchronous credential issuance."""

    def __init__(self, app, schema_said, recipient_pre, attributes, edges=None, rules=None,
                 codes=None, signal_bridge=None):
        """
        Initialize the IssueCredentialDoer.

        Args:
            app: Application instance
            schema_said: SAID of the credential schema
            recipient_pre: Prefix of the recipient identifier
            attributes: Dictionary of credential attributes
            edges: Dictionary of edge credential SAIDs (optional)
            rules: Dictionary of credential rules (optional)
            signal_bridge: DoerSignalBridge instance for emitting Qt signals
        """
        self.app = app
        self.hby = self.app.vault.hby
        self.rgy = self.app.vault.rgy
        self.schema_said = schema_said
        self.recipient_pre = recipient_pre
        self.attributes = attributes
        self.edges = edges or {}
        self.rules = rules or {}
        self.codes = codes or []
        self.signal_bridge = signal_bridge

        # Validate inputs
        if not schema_said:
            raise ValueError("Schema SAID is required")
        if not recipient_pre:
            raise ValueError("Recipient prefix is required")
        if not attributes:
            raise ValueError("Credential attributes are required")

        # Create generator-based doer
        doers = [doing.doify(self.issue_credential_do)]
        super(IssueCredentialDoer, self).__init__(doers=doers)

    def issue_credential_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for credential issuance.

        Args:
            tymth: Time function
            tock: Tick interval
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        # Create counselor, registrar, and postman for credential operations
        auths = {}
        if self.codes:
            code_time = helping.nowIso8601()
            for arg in self.codes:
                wit, code = arg.split(":")
                auths[wit] = f"{code}#{code_time}"

        counselor = grouping.Counselor(hby=self.hby)
        registrar = Registrar(hby=self.hby, rgy=self.rgy, counselor=counselor, auth=auths)
        postman = forwarding.Poster(hby=self.hby)
        verifier = verifying.Verifier(hby=self.hby, reger=self.rgy.reger)
        credentialer = credentialing.Credentialer(hby=self.hby, rgy=self.rgy, registrar=registrar,
                                                  verifier=verifier)

        self.extend([credentialer, counselor, registrar, postman])

        try:
            # Get the registry for this schema
            registry_name = self.schema_said
            registry = self.rgy.registryByName(self.schema_said)
            if not registry:
                raise Exception(f"Registry {registry_name} not found for schema {self.schema_said}")

            hab = registry.hab

            # Get the schema
            schemer = self.hby.db.schema.get(keys=(self.schema_said,))
            if not schemer:
                raise Exception(f"Schema {self.schema_said} not found")

            schema_title = schemer.sed.get('title', 'Untitled')

            logger.info(f"Issuing credential: {schema_title} from {hab.name} to {self.recipient_pre}")

            # Build the credential data structure
            # Add required system fields
            creder_data = {
                'i': self.recipient_pre,  # Issuee (recipient)
                'dt': coring.Dater().dts,  # Issuance datetime
            }

            schema = schemer.sed
            props = schema.get('properties', {})
            if 'a' not in props or 'oneOf' not in props['a']:
                raise Exception("Schema does not have a 'oneOf' array for attributes")

            one_of = props['a']['oneOf']

            # Find the object type (should be second element, index 1)
            attributes_obj = None
            for item in one_of:
                if isinstance(item, dict) and item.get('type') == 'object':
                    attributes_obj = item
                    break

            if not attributes_obj:
                raise Exception("Schema does not have a 'oneOf' object for attributes")

            # Get properties and required list
            properties = attributes_obj.get('properties', {})
            private = 'u' in properties

            # Add user-provided attributes
            creder_data.update(self.attributes)

            # Build edges block if edge credentials are specified
            edges_block = None
            if self.edges:
                edges_block = dict()
                edges_block['d'] = ""
                for edge_name, edge_def in self.edges.items():
                    edges_block[edge_name] = {
                        'n': edge_def['cred_said'],
                        's': edge_def['schema_said']
                    }

                _, edges_block = coring.Saider.saidify(sad=edges_block, kind=Kinds.json, label=coring.Saids.d)


            creder = credentialer.create(regname=registry_name,
                                         recp=self.recipient_pre,
                                         schema=self.schema_said,
                                         source=edges_block,
                                         rules=self.rules,
                                         data=self.attributes,
                                         private=private)

            dt = creder.attrib["dt"] if "dt" in creder.attrib else helping.nowIso8601()
            iserder = registry.issue(said=creder.said, dt=dt)

            # vcid = iserder.ked["i"]
            # rseq = coring.Seqner(snh=iserder.ked["s"])
            rseal = eventing.SealEvent(iserder.pre, iserder.snh, iserder.said)
            rseal = dict(i=rseal.i, s=rseal.s, d=rseal.d)

            if registry.estOnly:
                anc = hab.rotate(data=[rseal])

            else:
                anc = hab.interact(data=[rseal])

            aserder = serdering.SerderKERI(raw=anc)
            credentialer.issue(creder, iserder)
            registrar.issue(creder, iserder, aserder)

            acdc = signing.serialize(creder, coring.Prefixer(qb64=iserder.pre),
                                     core.Number(num=iserder.sn, code=core.NumDex.Huge),
                                     coring.Saider(qb64=iserder.said))

            if isinstance(hab, habbing.GroupHab):
                smids = hab.db.signingMembers(pre=hab.pre)
                smids.remove(hab.mhab.pre)

                for recp in smids:  # this goes to other participants only as a signaling mechanism
                    exn, atc = grouping.multisigIssueExn(ghab=hab, acdc=acdc, iss=iserder.raw, anc=anc)
                    postman.send(src=hab.mhab.pre,
                                      dest=recp,
                                      topic="multisig",
                                      serder=exn,
                                      attachment=atc)

            while not credentialer.complete(said=creder.said):
                self.rgy.processEscrows()
                verifier.processEscrows()
                credentialer.processEscrows()
                yield self.tock

            logger.info(f"Credential issued successfully: {creder.said}")

            # Emit success signal
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="IssueCredentialDoer",
                    event_type="credential_issued",
                    data={
                        'schema_title': schema_title,
                        'schema_said': self.schema_said,
                        'credential_said': creder.said,
                        'recipient_pre': self.recipient_pre,
                        'success': True
                    }
                )

            self.remove([counselor, registrar, postman])
            return

        except Exception as e:
            logger.exception(f"IssueCredentialDoer failed: {e}")

            # Emit failure signal
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="IssueCredentialDoer",
                    event_type="credential_issuance_failed",
                    data={
                        'error': str(e),
                        'schema_said': self.schema_said,
                        'recipient_pre': self.recipient_pre,
                        'success': False
                    }
                )

            # Clean up if we created any doers
            try:
                self.remove([counselor, registrar, postman])
            except:
                pass

            return


def outputCred(hby, rgy, said):
    out = bytearray()

    creder, *_ = rgy.reger.cloneCred(said=said)

    issr = creder.issuer
    out.extend(outputKEL(hby, issr))

    if creder.regid is not None:
        out.extend(outputTEL(rgy, creder.regid))
        out.extend(outputTEL(rgy, creder.said))

    chains = creder.edge if creder.edge is not None else {}
    saids = []
    for key, source in chains.items():
        if key == 'd':
            continue

        if not isinstance(source, dict):
            continue

        saids.append(source['n'])

    for said in saids:
        out.extend(outputCred(hby, rgy, said))

    (prefixer, seqner, saider) = rgy.reger.cancs.get(keys=(creder.said,))

    out.extend(signing.serialize(creder, prefixer, seqner, saider))

    return bytes(out)

def outputTEL(rgy, regk):
    out = bytearray()

    for msg in rgy.reger.clonePreIter(pre=regk):
        out.extend(msg)

    return bytes(out)

def outputKEL(hby, pre):
    out = bytearray()

    for msg in hby.db.clonePreIter(pre=pre):
        out.extend(msg)

    return bytes(out)

def escape_keys(obj):
    """Recursively escape $ and . in dictionary keys"""
    if isinstance(obj, dict):
        return {
            k.replace('$', '\uff04').replace('.', '\uff0e'):
                escape_keys(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [escape_keys(item) for item in obj]
    return obj

def unescape_keys(obj):
    """Recursively restore $ and . in dictionary keys"""
    if isinstance(obj, dict):
        return {
            k.replace('\uff04', '$').replace('\uff0e', '.'):
                unescape_keys(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [unescape_keys(item) for item in obj]
    return obj


def delete_credential(reger, said):
    saider = coring.Saider(qb64=said)
    creder = reger.creds.get(keys=(said,))
    if not creder:
        return False

    reger.creds.rem(keys=(said,))
    reger.cancs.rem(keys=(said,))

    subject = creder.attrib["i"].encode("utf-8")

    reger.issus.rem(keys=(creder.issuer,), val=saider)
    reger.subjs.rem(keys=(subject,), val=saider)
    reger.schms.rem(keys=(creder.schema,), val=saider)

    return True


class Registrar(doing.DoDoer):

    def __init__(self, hby, rgy, counselor, auth=None):
        self.hby = hby
        self.rgy = rgy
        self.counselor = counselor
        self.auth = auth
        self.receiptor = agenting.Receiptor(hby=self.hby)
        self.witPub = agenting.WitnessPublisher(hby=self.hby)

        doers = [self.receiptor, self.witPub, doing.doify(self.escrowDo)]

        super(Registrar, self).__init__(doers=doers)

    def incept(self, iserder, anc):
        """

        Parameters:
            iserder (SerderKERI): Serder object of TEL iss event
            anc (SerderKERI): Serder object of anchoring event

        Returns:
            Registry:  created registry

        """
        registry = self.rgy.regs[iserder.pre]
        hab = registry.hab
        rseq = core.Number(num=0, code=core.NumDex.Huge)

        if not isinstance(hab, GroupHab):  # not a multisig group
            seqner = core.Number(sn=hab.kever.sner.num)
            saider = coring.Diger(qb64=hab.kever.serder.said)
            registry.anchorMsg(
                pre=iserder.pre, regd=iserder.said, seqner=seqner, saider=saider
            )

            logger.info(f"Waiting for TEL event witness receipts for {anc.pre} - {seqner.sn}")
            msg = dict(pre=anc.pre, sn=seqner.sn)
            if self.auth:
                msg['auths'] = self.auth
            self.receiptor.msgs.append(msg)

            self.rgy.reger.tpwe.add(
                keys=(registry.regk, rseq.qb64),
                val=(hab.kever.prefixer, seqner, saider),
            )

        else:
            sn = anc.sn
            said = anc.said

            prefixer = coring.Prefixer(qb64=hab.pre)
            seqner = core.Number(sn=sn)
            saider = coring.Diger(qb64=said)

            self.counselor.start(
                prefixer=prefixer, number=seqner, diger=saider, ghab=hab
            )

            print("Waiting for TEL registry vcp event multisig anchoring event")
            self.rgy.reger.tmse.add(
                keys=(registry.regk, rseq.qb64, registry.regd),
                val=(prefixer, seqner, saider),
            )

    def issue(self, creder, iserder, anc):
        """
        Create and process the credential issuance TEL events on the given registry

        Parameters:
            creder (SerderACDC): credential to issue
            iserder (SerderKERI): Serder object of TEL iss event
            anc (SerderKERI): Serder object of anchoring event

        """
        regk = creder.regid
        registry = self.rgy.regs[regk]
        hab = registry.hab

        vcid = iserder.ked["i"]
        rseq = core.Number(num=iserder.ked["s"], code=core.NumDex.Huge)

        if not isinstance(hab, GroupHab):  # not a multisig group
            seqner = core.Number(sn=hab.kever.sner.num)
            saider = coring.Diger(qb64=hab.kever.serder.said)
            # Key is credential SAID and TEL event SAID
            registry.anchorMsg(
                pre=vcid, regd=iserder.said, seqner=seqner, saider=saider
            )

            print("Waiting for TEL event witness receipts")
            msg = dict(pre=hab.pre, sn=seqner.sn)
            if self.auth:
                msg['auths'] = self.auth

            logger.info(f"Waiting for TEL event witness receipts {hab.pre}")
            self.receiptor.msgs.append(msg)

            self.rgy.reger.tpwe.add(
                keys=(vcid, rseq.qb64), val=(hab.kever.prefixer, seqner, saider)
            )

        else:  # multisig group hab
            sn = anc.sn
            said = anc.said

            prefixer = coring.Prefixer(qb64=hab.pre)
            seqner = core.Number(sn=sn)
            saider = coring.Diger(qb64=said)

            self.counselor.start(
                prefixer=prefixer, number=seqner, diger=saider, ghab=hab
            )

            print(f"Waiting for TEL iss event multisig anchoring event {seqner.sn}")
            self.rgy.reger.tmse.add(
                keys=(vcid, rseq.qb64, iserder.said), val=(prefixer, seqner, saider)
            )

    def revoke(self, creder, rserder, anc):
        """
        Create and process the credential revocation TEL events on the given registry

        Parameters:
            creder (Creder): credential to issue
            rserder (Serder): Serder object of TEL rev event
            anc (Serder): Serder object of anchoring event
        """

        regk = creder.regid
        registry = self.rgy.regs[regk]
        hab = registry.hab

        vcid = rserder.ked["i"]
        rseq = core.Number(num=rserder.ked["s"], code=core.NumDex.Huge)

        if not isinstance(hab, GroupHab):  # not a multisig group
            seqner = core.Number(sn=hab.kever.sner.num)
            saider = coring.Diger(qb64=hab.kever.serder.said)
            registry.anchorMsg(
                pre=vcid, regd=rserder.said, seqner=seqner, saider=saider
            )

            print("Waiting for TEL event witness receipts")
            msg = dict(pre=hab.pre, sn=seqner.sn)
            if self.auth:
                msg['auths'] = self.auth
            self.receiptor.msgs.append(msg)

            self.rgy.reger.tpwe.add(
                keys=(vcid, rseq.qb64), val=(hab.kever.prefixer, seqner, saider)
            )
            return vcid, rseq.sn
        else:
            sn = anc.sn
            said = anc.said

            prefixer = coring.Prefixer(qb64=hab.pre)
            seqner = core.Number(sn=sn)
            saider = coring.Diger(qb64=said)

            self.counselor.start(
                prefixer=prefixer, number=seqner, diger=saider, ghab=hab
            )

            print(f"Waiting for TEL rev event multisig anchoring event {seqner.sn}")
            self.rgy.reger.tmse.add(
                keys=(vcid, rseq.qb64, rserder.said), val=(prefixer, seqner, saider)
            )
            return vcid, rseq.sn

    @staticmethod
    def multisigIxn(hab, rseal):
        ixn = hab.interact(data=[rseal])
        serder = serdering.SerderKERI(raw=bytes(ixn))

        sn = serder.sn
        said = serder.said

        prefixer = coring.Prefixer(qb64=hab.pre)
        seqner = coring.Seqner(sn=sn)
        saider = coring.Saider(qb64=said)

        return ixn, prefixer, seqner, saider

    def complete(self, pre, sn=0):
        """Determine if registry event (inception, issuance, revocation, etc.) is finished validation

        Parameters:
            pre (str): qb64 identifier of registry event
            sn (int): integer sequence number of regsitry event

        Returns:
            bool: True means event has completed and is commited to database
        """

        seqner = coring.Seqner(sn=sn)
        said = self.rgy.reger.ctel.get(keys=(pre, seqner.qb64))
        return said is not None and self.witPub.sent(said=pre)

    def escrowDo(self, tymth, tock=1.0, **kwa):
        """Process escrows of group multisig identifiers waiting to be compeleted.

        Steps involve:
           1. Sending local event with sig to other participants
           2. Waiting for signature threshold to be met.
           3. If elected and delegated identifier, send complete event to delegator
           4. If delegated, wait for delegator's anchor
           5. If elected, send event to witnesses and collect receipts.
           6. Otherwise, wait for fully receipted event

        Parameters:
            tymth (function): injected function wrapper closure returned by .tymen() of
                Tymist instance. Calling tymth() returns associated Tymist .tyme.
            tock (float): injected initial tock value.  Default to 1.0 to slow down processing

        """
        # enter context
        self.wind(tymth)
        self.tock = tock
        _ = yield self.tock

        while True:
            self.processEscrows()
            yield 0.5

    def processEscrows(self):
        """
        Process credential registry anchors:

        """
        self.processWitnessEscrow()
        self.processMultisigEscrow()
        self.processDiseminationEscrow()

    def processWitnessEscrow(self):
        """
        Process escrow of group multisig events that do not have a full compliment of receipts
        from witnesses yet.  When receipting is complete, remove from escrow and cue up a message
        that the event is complete.

        """
        for (regk, snq), (
                prefixer,
                number,
                diger,
        ) in self.rgy.reger.tpwe.getTopItemIter(keys=()):  # partial witness escrow
            kever = self.hby.kevers[prefixer.qb64]

            # Load all the witness receipts we have so far
            wigs = self.hby.db.wigs.get(keys=(prefixer.qb64b, diger.qb64))
            if kever.wits:
                if len(wigs) == len(
                        kever.wits
                ):  # We have all of them, this event is finished
                    hab = self.hby.habs[prefixer.qb64]
                    witnessed = False
                    for cue in self.receiptor.cues:
                        if cue["pre"] == hab.pre and cue["sn"] == number.sn:
                            witnessed = True

                    if not witnessed:
                        continue
                else:
                    continue

            rseq = core.Number(qb64=snq, code=core.NumDex.Huge)
            self.rgy.reger.tpwe.rem(keys=(regk, snq))

            self.rgy.reger.tede.add(
                keys=(regk, rseq.qb64), val=(prefixer, number, diger)
            )

    def processMultisigEscrow(self):
        """
        Process escrow of group multisig events that do not have a full compliment of receipts
        from witnesses yet.  When receipting is complete, remove from escrow and cue up a message
        that the event is complete.

        """
        for (regk, snq, regd), (
                prefixer,
                number,
                diger,
        ) in self.rgy.reger.tmse.getTopItemIter(keys=()):  # multisig escrow
            try:
                if not self.counselor.complete(prefixer, number, diger):
                    continue
            except kering.ValidationError:
                self.rgy.reger.tmse.rem(keys=(regk, snq, regd))
                continue

            rseq = core.Number(qb64=snq, code=core.NumDex.Huge)

            # Anchor the message, registry or otherwise
            key = dgKey(regk, regd)
            self.rgy.reger.ancs.put(keys=key, val=(core.Number(num=number.sn), diger))

            self.rgy.reger.tmse.rem(keys=(regk, snq, regd))
            self.rgy.reger.tede.add(
                keys=(regk, rseq.qb64), val=(prefixer, number, diger)
            )

    def processDiseminationEscrow(self):
        for (regk, snq), (
                prefixer,
                number,
                saider,
        ) in self.rgy.reger.tede.getTopItemIter(keys=()):  # group multisig escrow
            rseq = core.Number(qb64=snq, code=core.NumDex.Huge)
            dig = self.rgy.reger.tels.get(keys=regk, on=rseq.sn)
            if dig is None:
                continue

            self.rgy.reger.tede.rem(keys=(regk, snq))

            tevt = bytearray()
            for msg in self.rgy.reger.clonePreIter(pre=regk, fn=rseq.sn):
                tevt.extend(msg)

            print("Sending TEL events to witnesses")
            # Fire and forget the TEL event to the witnesses.  Consumers will have to query
            # to determine when the Witnesses have received the TEL events.
            self.witPub.msgs.append(dict(pre=prefixer.qb64, said=regk, msg=tevt))
            self.rgy.reger.ctel.put(keys=(regk, rseq.qb64), val=saider)  # idempotent
