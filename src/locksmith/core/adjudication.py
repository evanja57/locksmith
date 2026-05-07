# -*- encoding: utf-8 -*-
"""
locksmith.core.adjudication module

"""
import random

from hio.base import doing
from hio.help import decking
from keri import help
from keri.app import watching
from keri.app.agenting import httpClient
from keri.app.httping import Clienter, streamCESRRequests
from keri.core import eventing, routing, parsing

from locksmith.core.remoting import message_version

logger = help.ogler.getLogger(__name__)


class Watchmen(doing.DoDoer):
    """ Who watches the Watchmen """

    def __init__(self, hby, tock=None, **kwa):
        self.cues = decking.Deck()

        self.ksqs = decking.Deck()
        inquisitor = Rorschach(hby=hby, cues=self.cues, ksqs=self.ksqs, tock=tock)
        doers = [inquisitor]
        super(Watchmen, self).__init__(doers=doers, **kwa)

    def recur(self, tyme, deeds=None):
        if self.ksqs:
            ksq = self.ksqs.pull()
            self.extend([ksq])

        super(Watchmen, self).recur(tyme, deeds)


class Rorschach(doing.Doer):

    def __init__(self, hby, ksqs, cues=None, **kwa):
        self.hby = hby
        self.ksqs = ksqs
        self.cues = cues if cues is not None else decking.Deck()

        super(Rorschach, self).__init__(**kwa)
        
    def recur(self, tyme, deeds=None):
        watched = dict()
        for (cid, wid, oid), obr in self.hby.db.obvs.getTopItemIter():
            if (cid, oid) not in watched:
                watched[(cid, oid)] = list()
            watched[(cid, oid)].append(wid)

        for (cid, oid), wids in watched.items():
            hab = self.hby.habByPre(cid)
            logger.info(f"Querying watchers={wids} for key state of {oid} as {hab.pre}")
            ksq = KeyStateQuerier(hby=self.hby, hab=hab, wids=wids, oid=oid, cues=self.cues)
            self.ksqs.append(ksq)

        return False


class KeyStateQuerier(doing.DoDoer):

    def __init__(self, hby, hab, oid, wids, cues, **opts):
        self.hby = hby
        self.hab = hab
        self.oid = oid
        self.wids = wids
        self.cues = cues

        doers = []
        self.saiders = dict()
        for wid in self.wids:
            keys = (self.oid, wid)
            saider = self.hby.db.knas.get(keys)
            if saider is not None:
                self.saiders[keys] = saider
                self.hby.db.knas.rem(keys)

            logger.info(f"Launching the inquisition for {self.oid} from {wid}:")

            self.witq = WatcherInquisitor(hby=self.hby)
            self.witq.query(hab=self.hab, pre=self.oid, r="ksn", wit=wid)
            doers.append(self.witq)

        super(KeyStateQuerier, self).__init__(doers=doers, **opts)

    def recur(self, tyme, deeds=None):
        """
        Returns:  doifiable Doist compatible generator method
        Usage:
            add result of doify on this method to doers list
        """

        adjudicate = False
        for wid in self.wids:
            keys = (self.oid, wid)

            if (saider := self.hby.db.knas.get(keys)) is None:
                return super(KeyStateQuerier, self).recur(tyme, deeds)
            else:
                logger.info(f"Watcher {wid} reports {saider.qb64} as the current state of {self.oid}")
                if keys in self.saiders and self.saiders[keys].qb64 != saider.qb64:
                    adjudicate = True

        if adjudicate:
            adj = watching.Adjudicator(hby=self.hby, hab=self.hab, cues=self.cues)
            adj.adjudicate(self.oid)

        else:
            logger.info(f"State for {self.oid} for all watchers of {self.hab.pre} remains unchanged")

        return True


class KeyStateVarianceAuthority(doing.DoDoer):

    def __init__(self, hby, notifier, cues=None):
        self.hby = hby
        self.notifier = notifier
        self.cues = cues if cues is not None else decking.Deck()
        super(KeyStateVarianceAuthority, self).__init__(doers=[], always=True, tock=1.0)

    def recur(self, tyme, deeds=None):
        if self.cues:
            cue = self.cues.pull()
            kin = cue['kin']

            match kin:
                case "keyStateConsistent":
                    pass  # This is the usual case and is logged in the adjudicator

                case "keyStateLagging":
                    pass  # Eventually we'll need reporting of this, but it is not logged in the adjudicator

                case "keyStateUpdate":
                    ahds = cue["aheads"]
                    cid = cue["cid"]

                    state = random.choice(ahds)
                    hab = self.hby.habs[cid]
                    fn = self.hby.kevers[state.pre].sn + 1

                    logger.info(f"Submitting query for {state.pre} as seq no. {state.sn} to {state.wit}")
                    querier = SeqNoQuerier(hby=self.hby, hab=hab, pre=state.pre, fn=fn, sn=state.sn, wit=state.wit)
                    notify_doer = NotifyDoer(hby=self.hby, notifier=self.notifier, state=state)
                    self.extend([querier, notify_doer])

                case "keyStateDuplicitous":
                    pass  # Eventually we'll need to halt processing until this is resolved.

        return super(KeyStateVarianceAuthority, self).recur(tyme, deeds)


class SeqNoQuerier(doing.DoDoer):

    def __init__(self, hby, hab, pre, sn, fn=None, wit=None, **opts):
        self.hby = hby
        self.hab = hab
        self.pre = pre
        self.sn = sn
        self.fn = fn if fn is not None else 0
        self.witq = WatcherInquisitor(hby=self.hby)
        self.witq.query(src=self.hab.pre, pre=self.pre,
                        fn="{:x}".format(self.fn),
                        sn="{:x}".format(self.sn),
                        wit=wit)
        super(SeqNoQuerier, self).__init__(doers=[self.witq], **opts)

    def recur(self, tyme, deeds=None):
        """
        Returns:  doifiable Doist compatible generator method
        Usage:
            add result of doify on this method to doers list
        """
        if self.pre not in self.hab.kevers:
            return False

        kever = self.hab.kevers[self.pre]
        if kever.sn >= self.sn:
            self.remove([self.witq])
            return True

        return super(SeqNoQuerier, self).recur(tyme, deeds)


class WatcherInquisitor(doing.DoDoer):

    def __init__(self, hby, msgs=None, cues=None):

        self.hby = hby
        rtr = routing.Router()
        rvy = routing.Revery(db=self.hby.db, rtr=rtr)
        kvy = eventing.Kevery(db=hby.db, lax=True, rvy=rvy)
        kvy.registerReplyRoutes(router=rtr)
        self.kvy = kvy
        self.rvy = rvy
        self.msgs = msgs if msgs is not None else decking.Deck()
        self.cues = cues if cues is not None else decking.Deck()
        self.clienter = Clienter()

        doers = [self.clienter, doing.doify(self.wit_do)]

        super(WatcherInquisitor, self).__init__(doers=doers)

    def execute(self, target, src, route, query, wat):
        """ Returns a generator for watcher querying

        The returns a generator that will submit the query to the watcher using
        the synchronous watcher API, then parse the results.


        Parameters:
            target (str): qualified base64 identifier to query for
            src (str): qb64 identifierof the query submitter
            route (str): query route, ie. /logs, /ksn
            query (dict): additional query params
            wat (str): watcher to query

        Returns:
            list: identifiers of witnesses that returned receipts.

        """
        if (hab := self.hby.habByPre(src)) is None:
            return

        try:
            client, client_doer = httpClient(hab, wat)
            self.extend([client_doer])
        except Exception as e:
            logger.exception(f"unable to create http client for witness {wat}: {e}")
            return

        msg = hab.query(target, src=wat, route=route, query=query)  # Query for remote pre Event
        streamCESRRequests(client=client, dest=wat, ims=bytearray(msg), path="/", headers=dict())
        while not client.responses:
            yield self.tock

        rep = client.respond()
        if rep.status == 200:
            rpy = bytearray(rep.body)
            parsing.Parser(
                framed=True,
                kvy=self.kvy,
                rvy=self.rvy,
                local=True,
                version=message_version(rpy),
            ).parse(bytearray(rpy))

        elif rep.status == 204:
            logger.debug(
                f"watcher {wat} accepted key-state query for {target} without an inline response"
            )

        else:
            logger.info(f"invalid response {rep.status} from watcher {wat}")

        self.remove([client_doer])

        return

    def wit_do(self, tymth=None, tock=0.0, **kwa):
        """
         Returns doifiable Doist compatibile generator method (doer dog) to process
            .kevery and .tevery escrows.

        Parameters:
            tymth (function): injected function wrapper closure returned by .tymen() of
                Tymist instance. Calling tymth() returns associated Tymist .tyme.
            tock (float): injected initial tock value

        Usage:
            add result of doify on this method to doers list
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        while True:
            while self.msgs:
                msg = self.msgs.popleft()
                target = msg["target"]
                src = msg["src"]
                r = msg["r"]
                q = msg["q"]
                wat = msg["wit"]

                yield from self.execute(target, src, route=r, query=q, wat=wat)
                self.cues.push(msg)

            yield self.tock

    def query(self, pre, r="logs", sn='0', fn='0', src=None, hab=None, anchor=None, wit=None):
        """ Create, sign and return a `qry` message against the attester for the prefix

        Parameters:
            src (str): qb64 identifier prefix of source of query
            hab (Hab): Hab to use instead of src if provided
            pre (str): qb64 identifier prefix being queried for
            r (str): query route
            sn (str): optional specific hex str of sequence number to query for
            fn (str): optional specific hex str of sequence number to start with
            anchor (Seal): anchored Seal to search for
            wit (str) watcher qv94 prefix to query

        Returns:
            bytearray: signed query event

        """
        qry = dict(s=sn, fn=fn)
        if anchor is not None:
            qry["a"] = anchor

        msg = dict(src=src, pre=pre, target=pre, r=r, q=qry, wit=wit)
        if hab is not None:
            msg["src"] = hab.pre

        self.msgs.append(msg)

class NotifyDoer(doing.Doer):

    def __init__(self, hby, notifier, state, **kwa):
        self.hby = hby
        self.notifier = notifier
        self.state = state
        super(NotifyDoer, self).__init__(**kwa)

    def recur(self, tyme=0.0, deeds=None):
        while not self.hby.kevers[self.state.pre].sn >= self.state.sn:
            yield 5.0

        msg = dict(
            r='/keystate/update',
            pre=self.state.pre,
            sn=self.state.sn,
            dig=self.state.dig
        )

        # Notify controller of sucessful challenge
        self.notifier.add(msg)

        return True
