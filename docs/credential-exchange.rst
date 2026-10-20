Send a credential in Locksmith
==============================

Use two wallets: one issuer and one holder. The issuer creates and sends the
credential. The holder reviews it and adds it to their wallet.

This example uses the bundled SEDI IAR schema with an issuer KEL anchor. It does
not need a registrar or observer.

Setup
-----

Install Locksmith using the :doc:`developer-guide`. Start kf-boot and its witness
and watcher services. See :doc:`kerifoundation-plugin` for service configuration
and links to the server instructions. The default configuration uses localhost,
so run both wallets and the services on the same computer.

From the Locksmith repository, run this in the issuer terminal:

.. code-block:: bash

   LOCKSMITH_BASE=issuer uv run --locked python -m locksmith.main

Run this in the holder terminal:

.. code-block:: bash

   LOCKSMITH_BASE=holder uv run --locked python -m locksmith.main

LOCKSMITH_BASE selects a storage base under the normal KERI data directories.
Use a simple name, such as 'issuer'. Each wallet will list the vaults in its
own base. Use the same command when you reopen it. If you omit LOCKSMITH_BASE,
Locksmith uses the default base. Changing the base does not move existing vaults.

Create the vaults
-----------------

1. In the issuer wallet, open Vaults → Initialize New Vault. Name it Demo Issuer,
   enter a passcode (or leave it blank for no password; I prefer this for demoing
   locally), and click Create. Open the vault.
2. Do the same in the holder wallet with the name Demo Holder.
3. In each vault, open KERI Foundation. Under Account AID, create an account
   identifier. Use the alias issuer in the first wallet and holder in the second.
4. Select the 1-of-1 witness profile and click Begin Onboarding. Wait for COMPLETED.
5. Scan each wallet's witness QR code with your authenticator.
6. Click Open Account.

Connect the wallets
-------------------

In each wallet, open Local Identifiers, find the account identifier, and choose
⋮ → Export. Save the files as issuer.cesr and holder.cesr. Export after onboarding
so the files include the current signed delivery routes.

1. Open Remote Identifiers → Add Remote Identifier → File.
2. In the issuer wallet, import holder.cesr with the alias holder. In the holder
   wallet, import issuer.cesr with the alias issuer.

Load the schema
---------------

In both wallets:

1. Open Credentials → Schema → Add Schema.
2. Select Built-in → SEDI IAR Schema.
3. In the issuer wallet, check Use for Credential Issuance and select issuer.
   Leave it unchecked in the holder wallet.
4. Click Load Schema.

Issuer: create the credential
-----------------------------

1. Open Credentials → Issued Credentials → Issue Credential.
2. Select SEDI IAR Schema.
3. Set Issuer authentication to Issuer KEL anchor.
4. Select Remote Identifier, then holder as the recipient.
5. Enter something for Given Name, Family Name, and Date of birth.

The other text fields can be blank for this example. This includes the residence
fields, Facial image SAID, and Proofing session datetime. The IAR schema accepts
these blanks. Other schemas can have different requirements.

Click Issue Credential. If witness authentication appears, enter the issuer's
current code and click Authenticate. Wait for Credential created.

Issuer: send it
---------------

1. Click Grant. If you closed the creation dialog, use
   Issued Credentials → ⋮ → Grant.
2. Check that To is holder. Expand Review data and terms to share and check the
   values.
3. Leave delivery set to Send and click Send credential.

Holder: accept it
-----------------

1. Open Credentials → Activity → Received. Click Refresh if needed.
2. Open the new exchange. Check the issuer, recipient, values, and terms.
3. Click Add credential.

The holder saves the credential and sends an acknowledgment to the issuer.

Check the result
----------------

1. The holder's Received Credentials list shows the credential as Authenticated.
2. The issuer's Issued Credentials list contains the matching credential.
   Compare the full credential SAID in both wallets.
3. Activity history shows Accepted in both wallets. Use Issued on the issuer
   side and Received on the holder side. Submitted does not confirm acceptance.
4. Use Close Vault, close the app windows, then reopen the same vaults with the
   same storage bases. The credential and accepted history should still be there.

Other IPEX flows
----------------

The steps above use Grant → Admit. To try Offer → Agree → Grant → Admit with the
same IAR credential:

1. Issuer: choose Issued Credentials → ⋮ → Offer, select holder, and click
   Send offer.
2. Holder: open the Offer in Activity → Received and click Agree and request.
3. Issuer: open the updated exchange in Activity → Issued, review the data to
   share, and click Send credential.
4. Holder: review the values and click Add credential.
5. Check Accepted in both histories.

Offer shares the issuer, credential type, and public terms. The credential values
arrive with Grant. This creates another exchange of the same credential. Use the
IAR credential without linked credentials for this flow.

To start with Apply, the holder chooses Received Credentials → Apply for
credential…. Select the issuer and schema, then click Send application. The
issuer opens Review application, creates or selects a credential, and chooses
Send credential or Send offer. Continue with the matching steps above.
