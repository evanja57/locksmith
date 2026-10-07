# -*- encoding: utf-8 -*-
"""
locksmith.core.vaulting module

Vault management for Locksmith application
"""
from PySide6.QtCore import QTimer
from hio.base import doing
from hio.help import decking
from keri import help
from keri.app import (
    agenting,
    organizing,
    delegating,
    forwarding,
    grouping,
    habbing,
    notifying,
    oobiing,
    signaling,
)
from keri.core import routing as keriRouting, eventing, coring, kraming
from keri.peer import exchanging

from locksmith.core import indirecting, challenging, ipexing
from locksmith.core.adjudication import Watchmen, KeyStateVarianceAuthority
from locksmith.core.configing import ENABLE_TURRET_BROWSER_PLUGIN
from locksmith.core.grouping import CounselingCompletionDoer
from locksmith.core.receipting import LocksmithReceiptor
from locksmith.core.signals import DoerSignalBridge
from locksmith.core.tasking import QtTask
from locksmith.core.turretting import TurretDoer
from locksmith.db.basing import LocksmithBaser, MailboxListener, BrowserPluginSettings

logger = help.ogler.getLogger(__name__)


class Vault(doing.DoDoer):
    """
    The top level object and DoDoer representing a Habery for a
    remote controller and all associated processing.

    This is a minimal implementation that will be expanded as needed.
    """

    def __init__(self, app, hby, rgy):
        """
        Initialize the Vault with core KERI components.

        Args:
            app: Application instance
            hby: Habery instance
            rgy: Regery instance
        """
        self.app = app
        self.hby = hby
        self.closed = False
        # The app closes registry and message stores before the Habery.
        self.hby.free = False
        self.rgy = rgy
        config = hby.cf.get()
        config['kram'] = {
            'enabled': True,
            'caches': {'~': (10000, 300000, 3600000, 86400000, 300000, 3600000, 86400000)},
            'denials': [[[2, 0], 'qry', ''], [[2, 0], 'rpy', ''],
                        [[2, 0], 'exn', '/multisig'], [[2, 0], 'exn', '/challenge']],
        }
        hby.cf.put(config)
        self.kram_cues = decking.Deck()
        self.kramer = kraming.Kramer(db=hby.db, cf=hby.cf, cues=self.kram_cues)
        self.db = LocksmithBaser(
            name=self.hby.name,
            base=self.hby.base,
            temp=self.hby.temp,
            reopen=True,
        )

        # Keyed namespace for plugin runtime state
        self.plugin_state: dict[str, any] = {}

        # Browser plugin settings (loaded from db if exists)
        self.pluginSettings: BrowserPluginSettings | None = self.db.pluginSettings.get(keys=("default",))
        if ENABLE_TURRET_BROWSER_PLUGIN and not self.pluginSettings:
            self.pluginSettings = BrowserPluginSettings("", f"plugin-{self.hby.name}", None)
            if (hab := self.hby.habByName(self.pluginSettings.locksmith_alias, ns="settings")) is None:
                hab = self.hby.makeHab(name=self.pluginSettings.locksmith_alias,
                                       transferable=True,
                                       ns="settings")
            self.pluginSettings.locksmith_identifier = hab.pre
            self.db.pluginSettings.pin(keys=("default",), val=self.pluginSettings)

        # Signal bridge for doer-to-UI communication
        self.signals = DoerSignalBridge()

        # Core components
        self.swain = delegating.Anchorer(hby=hby)
        self.counselor = grouping.Counselor(hby=hby, swain=self.swain)
        self.org = organizing.Organizer(hby=hby)

        # Message queues for inter-component communication
        self.cues = decking.Deck()
        self.groups = decking.Deck()
        self.anchors = decking.Deck()
        self.witners = decking.Deck()
        self.queries = decking.Deck()
        self.exchanges = decking.Deck()

        # OOBI manager
        oobiery = oobiing.Oobiery(hby=hby)

        # Core KERI doers
        self.receiptor = LocksmithReceiptor(hby=hby)
        self.postman = forwarding.Poster(hby=hby)
        self.witPub = agenting.WitnessPublisher(hby=self.hby)
        self.witDoer = agenting.WitnessReceiptor(hby=self.hby)

        # Mailbox and storage
        from keri.app import storing
        self.rep = storing.Respondant(
            hby=hby,
            cues=self.cues,
            mbx=storing.Mailboxer(
                name=self.hby.name,
                base=self.hby.base,
                temp=self.hby.temp,
            ),
        )

        # Habery doer
        self.hbyDoer = habbing.HaberyDoer(habery=hby)

        # Signaling and notifications
        signaler = signaling.Signaler()
        self.notifier = notifying.Notifier(
            hby=hby,
            signaler=signaler,
            noter=notifying.Noter(
                name=self.hby.name,
                base=self.hby.base,
                temp=self.hby.temp,
            ),
        )
        self.mux = grouping.Multiplexor(hby=hby, notifier=self.notifier)

        # Exchange handling
        self.exc = exchanging.Exchanger(hby=hby, handlers=[])

        # Load protocol handlers
        grouping.loadHandlers(exc=self.exc, mux=self.mux)
        for verb in ('apply', 'offer', 'agree', 'grant', 'admit', 'spurn'):
            self.exc.addHandler(ipexing.IpexHandler(f'/ipex/{verb}', hby, self.notifier, rgy,
                                                  signals=self.signals))
        challenging.loadHandlers(db=self.hby.db, exc=self.exc, notifier=self.notifier)

        # KEL and credential verification
        self.rvy = keriRouting.Revery(db=hby.db, cues=self.cues)
        self.kvy = eventing.Kevery(db=hby.db, lax=True, local=False, rvy=self.rvy,
                                  cues=self.cues, kramer=self.kramer, exc=self.exc)
        self.kramer.cues = self.kram_cues
        self.kvy.registerReplyRoutes(router=self.rvy.rtr)

        watchmen = Watchmen(hby=hby, tock=15.0)
        kva = KeyStateVarianceAuthority(hby=hby, notifier=self.notifier, cues=watchmen.cues)

        # Mailbox director
        self.mbx = indirecting.MailboxDirector(
            hby=self.hby,
            topics=['/receipt', '/multisig', '/replay', '/delegate', '/credential', '/challenge', '/reply'],
            exc=self.exc,
            kvy=self.kvy,
            rvy=self.rvy,
            rgy=self.rgy,
        )

        # Notification toast doer
        self.toast_doer = NotificationToastDoer(vault=self)
        self.ipex_outbox = ipexing.IpexOutboxDoer(self)
        self.turrent_doer: TurretDoer | None = None
        if ENABLE_TURRET_BROWSER_PLUGIN and self.pluginSettings is not None:
            self.turrent_doer = TurretDoer(self.hby,
                                           self.rgy,
                                           self.pluginSettings.locksmith_alias,
                                           self.pluginSettings.plugin_identifier)

        # Assemble all doers
        self.doers = [
            self.hbyDoer,
            self.receiptor,
            self.postman,
            self.witPub,
            self.rep,
            self.swain,
            self.counselor,
            self.witDoer,
            *oobiery.doers,
            watchmen,
            kva,
            self.mbx,
            self.ipex_outbox,
            kraming.Pruner(self.kramer, tock=1.0),
            self.toast_doer,
        ]
        if self.turrent_doer is not None:
            self.doers.append(self.turrent_doer)
        # Initialize DoDoer with always=True to keep running
        super(Vault, self).__init__(doers=self.doers, always=True)

        # Add counseling doers for group identifiers awaiting participant signatures
        self.counseling_completion_doers = {}
        for (pre,), (seqner, saider) in self.hby.db.gpse.getTopItemIter(keys=()):
            prefixer = coring.Prefixer(qb64=pre)
            hab = self.hby.habByPre(pre)

            counseling_completion_doer = CounselingCompletionDoer(
                self, prefixer, seqner, hab)
            self.counseling_completion_doers[pre] = counseling_completion_doer
            logger.info(f"Found group awaiting participant signatures: {prefixer.qb64} "
                        f"(alias: {hab.name}, sn: {seqner.sn})")

        self.doers.extend(list(self.counseling_completion_doers.values()))

        logger.info(f"Vault initialized for {hby.name} with {len(self.doers)} doers")

    def load_active_mailboxes(self):
        """Load active mailbox listeners from db."""
        for (eid,), mbl in self.db.mbx.getTopItemIter():
            hab = self.hby.habByPre(mbl.cid)
            if hab is not None:
                self.activate_mailbox(hab, mbl.name, eid)

    def activate_mailbox(self, hab, mailbox_name, mailbox_eid):
        mbl = MailboxListener(cid=hab.pre, eid=mailbox_eid, name=mailbox_name)
        self.db.mbx.pin(keys=(mailbox_eid,), val=mbl)

        self.mbx.add_poller(hab=hab, mailbox=mailbox_eid)

    def deactivate_mailbox(self, hab, mailbox_eid):
        self.db.mbx.rem(keys=(mailbox_eid,))
        self.mbx.remove_poller(hab=hab, mailbox=mailbox_eid)

    def update_plugin_identifier(self, plugin_identifier):
        if not ENABLE_TURRET_BROWSER_PLUGIN:
            return None

        settings = self.db.pluginSettings.get(keys=("default",))
        if settings is None:
            return None

        settings.plugin_identifier = plugin_identifier
        self.db.pluginSettings.pin(keys=("default",), val=settings)
        if self.turrent_doer is None:
            return None

        self.turrent_doer.set_plugin_identifier(plugin_identifier)


class NotificationToastDoer(doing.Doer):
    """
    Doer for detecting new notifications and triggering toast displays.

    Polls the notifier for new unread notifications and emits signals
    when new ones are detected.
    """

    def __init__(self, vault, **kwa):
        """
        Initialize the NotificationToastDoer.

        Args:
            vault: Vault instance with notifier and signal bridge
        """
        super().__init__(tock=3.0, **kwa)  # Check every 3 seconds
        self.vault = vault
        self._seen_notifications = set()

    def enter(self, **kwa):
        """Called when doer starts."""
        logger.info("NotificationToastDoer started")
        self._remember_notifications()
        self.vault.load_active_mailboxes()

    def recur(self, tyme):
        """Called every tock (3 seconds) to check for new notifications."""
        try:
            notes = list(self.vault.notifier.noter.notes.getTopItemIter())
            unread_count = sum(not note.read for _, note in notes)
            arrived = [(rid, note) for (_, rid), note in notes
                       if rid not in self._seen_notifications and not note.read]
            self._seen_notifications = {rid for (_, rid), _ in notes}
            for rid, note in arrived:
                self.vault.signals.emit_doer_event(
                    doer_name='NotificationToast', event_type='new_notification',
                    data={'datetime': note.datetime, 'message': self._format_notification_message(note),
                          'pending_count': unread_count, 'rid': rid})

        except Exception as e:
            logger.exception(f"Error in NotificationToastDoer: {e}")

        return False  # Continue running

    def _remember_notifications(self):
        """Treat retained notices as history when a vault opens."""
        self._seen_notifications = {rid for (_, rid), _ in self.vault.notifier.noter.notes.getTopItemIter()}

    def _format_notification_message(self, note):
        """
        Format notification message for display in toast.

        Args:
            note: Notification object

        Returns:
            Formatted message string
        """
        # Check the notification route
        route = note.pad.get('a', {}).get('r', '')

        # Check if this is a multisig notification
        if '/multisig' in route:
            if '/multisig/icp' in route:
                return "New multisig group proposal"
            elif '/multisig/rot' in route:
                return "Multisig rotation request"
            elif '/multisig/ixn' in route:
                return "Multisig interaction request"
            else:
                return "New multisig notification"

        if "/challenge/response" in route:
            signer = note.pad.get('a', {}).get('signer', '')
            org = organizing.Organizer(hby=self.vault.hby)
            signer_contact = org.get(signer)
            if signer_contact is None:
                signer_name = "Unknown"
            else:
                signer_name = signer_contact.get('alias', 'Unknown')
            return f"Challenge response received from {signer_name}"

        if "/keystate/update" in route:
            pre = note.pad.get('a', {}).get('pre', '')
            sn = note.pad.get('a', {}).get('sn', '')
            dig = note.pad.get('a', {}).get('dig', '')
            org = organizing.Organizer(hby=self.vault.hby)
            signer_contact = org.get(pre)
            if signer_contact is None:
                signer_name = "Unknown"
            else:
                signer_name = signer_contact.get('alias', 'Unknown')
            return f"Key state update recieved for {signer_name} moving to sequence number {sn} at {dig}"

        # Check if this is an IPEX notification
        if route.startswith('/exn/ipex'):
            # Try to get IPEX-specific details
            attrs = note.attrs
            said = attrs.get('d', '')

            if said:
                try:
                    from keri.peer import exchanging
                    exn, _ = exchanging.cloneMessage(self.vault.hby, said)
                    if exn:
                        hab = self.vault.hby.habByPre(exn.pre)
                        contact = self.vault.org.get(exn.pre) or {}
                        sender = hab.name if hab else contact.get('alias', exn.pre[:10] + '…')
                        stage = exn.route.rsplit('/', 1)[-1].title()
                        title = 'Credential exchange'
                        tip = exn
                        while tip is not None:
                            requested = ipexing.request_schema(tip)
                            cached = self.vault.hby.db.schema.get((requested,)) if requested else None
                            if cached:
                                title = cached.sed.get('title', title)
                                break
                            origins = tip.sad['a'].get('o', [])
                            if origins:
                                nests = exchanging.loadParsedNestedSubstreams(self.vault.hby, tip.said)
                                nest = next((item for item in nests if item.serder.said == origins[0]), None)
                                if nest:
                                    schema = nest.serder.schema
                                    cached = self.vault.hby.db.schema.get((schema,)) if isinstance(schema, str) else None
                                    schema = cached.sed if cached else schema
                                    if isinstance(schema, dict):
                                        title = schema.get('title', title)
                                    break
                            tip = self.vault.hby.db.exns.get((tip.sad['p'],)) if tip.sad['p'] else None
                        return f'{stage} from {sender}: {title}'
                except Exception as e:
                    logger.warning(f"Error formatting IPEX notification: {e}")

        # Fallback to generic message
        if isinstance(note.attrs, dict):
            return note.attrs.get('message',
                                  note.attrs.get('msg',
                                                 note.attrs.get('d', 'New notification')))
        return str(note.attrs) if note.attrs else "New notification"

    def exit(self):
        """Called when doer exits."""
        logger.info("NotificationToastDoer stopped")



def run_vault_controller(app, hby, rgy, expire=0.0):
    """
    Creates a Vault and runs it with a QtTask.

    Args:
        app: Application instance
        hby: Habery instance
        rgy: Regery instance
        expire (float): Time limit for running (0.0 means no limit)

    Returns:
        tuple: (vault, qtask) - Vault instance and QtTask instance
    """
    try:
        vault = Vault(app=app, hby=hby, rgy=rgy)
    except Exception:
        rgy.close()
        hby.close()
        raise
    doers = [vault]

    tock = 0.03125  # ~31.25ms tick rate
    doist = doing.Doist(doers=doers, limit=expire, tock=tock, real=True)

    timer = QTimer()
    qtask = QtTask(doist=doist, timer=timer, limit=expire)

    timer.timeout.connect(qtask.run)
    timer.start(int(tock * 1000))  # Convert to milliseconds

    logger.info(f'Vault controller running for {hby.name}')

    return vault, qtask
