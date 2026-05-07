# -*- encoding: utf-8 -*-
"""
locksmith.core.receipting module

Locksmith-local witness receipting compatibility helpers.
"""
from keri.app import agenting, httping
from keri import kering


class LocksmithReceiptor(agenting.Receiptor):
    """Receiptor with fixed witness catch-up behavior.

    keripy replays new-witness catch-up one event at a time and only waits
    for the first HTTP response before tearing down the client. When a controller
    already has witnessed history, newly added witnesses can miss later replayed
    events and then reject the next `/receipts` request with HTTP 202.

    Locksmith only overrides the broken replay strategy here: send the full
    KEL replay in one burst, wait for all HTTP responses, then drain them
    before removing the client doer.
    """

    def catchup(self, pre, wit):
        if pre not in self.hby.prefixes:
            raise kering.MissingEntryError(f"{pre} not a valid AID")

        hab = self.hby.habs[pre]
        client, client_doer = agenting.httpClient(hab, wit)
        self.extend([client_doer])

        try:
            sent = httping.streamCESRRequests(
                client=client,
                dest=wit,
                ims=bytearray(hab.replay(pre=pre)),
            )
            while len(client.responses) < sent:
                yield self.tock

            while client.responses:
                client.respond()
        finally:
            self.remove([client_doer])
