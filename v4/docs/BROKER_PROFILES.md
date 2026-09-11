# Broker profiles (v4 0.9.1)

## Choose a login, then an account

Click **Choose broker login** in the main controls, or open **Broker accounts**.
Choose a platform name from **Platform** and click **Log in** beside it.
The backend uses that profile's credentials to obtain the broker's
account list. Choose one under **Available trading accounts**, then click
**Use selected account** to authenticate its account session and load its card.

`MTR_PLATFORM_NAME` and `GTR_PLATFORM_NAME` provide friendly display labels.
Mixed-case names such as `MTR_Platform_name` and `GTR_platform_name` are supported.
Only the friendly name is shown in the first dropdown. The prefix is used internally
to select credentials. Restart after editing .env. Only the selected platform's
status, account dropdown and account card are shown. The account dropdown sits
below the platform/login row and appears after successful authentication.

Account IDs may be blank for this two-step flow, including the primary account at
startup. Discovery opens and closes a temporary login connection without adopting
a trading account. The authenticated response is retained only in backend memory.
Selection reuses it when its token expiry is in the future. Expired logins hide
account choices and offer **Refresh login**, which performs a fresh password login.
Expiry is checked again before account selection. Unknown expiry is explicitly
labeled, and selection then performs a fresh account login. Broker failures
invalidate the cached login and choices. JWT expiry is a freshness check, not a
guarantee against broker revocation. Only IDs
and demo markers reach the account list, never credentials or tokens. Session
expiration is displayed when the broker supplies a readable expiry.

Switching a profile closes its previous selected session, clears its snapshots
and connects the newly selected account. Other profiles stay connected. MTR uses
the primary workspace and requires capture stopped before switching. GTR and
other profiles retain separate account cards and read sessions; selecting one
does not change the primary copy destination. Disconnect clears discovered choices.

The sections below also describe the original direct-connect controls, which
still require a configured account ID.

Run the dashboard from v4 as usual and open **Broker accounts**. It supports up to
five concurrently connected broker accounts: the existing MTR profile and four
additional prefixes. Profile detection uses populated PREFIX_PLATFORM_URL fields
from .env plus process environment overrides. Prefixes contain uppercase letters
and digits, beginning with a letter. More than five or duplicate identities are
rejected at startup. Restart the application after changing its configuration.

Each profile supplies its own complete settings; credentials are never inherited
from MTR. Example for a second broker (placeholders only):

```dotenv
GTR_PLATFORM_URL=https://broker.example
GTR_EMAIL=your-broker-email
GTR_PASSWORD=your-broker-password
GTR_BROKER_ID=your-broker-id
GTR_ACCOUNT_ID=your-trading-account-id
GTR_COOKIE_MODE=session
GTR_TLS_MINIMUM_VERSION=TLSv1.3
```

Use THIRD_, FOURTH_ and FIFTH_ similarly, or other distinct prefixes. An explicit
account ID is required before a card can connect. A blank ID produces a per-profile
configuration message instead of choosing an account returned by login. Even with
the same broker/login you can use multiple profiles with different account IDs.
Existing MTR_ACCOUNT_IDS remains the legacy primary-workspace selector; it does
not create independently connected profiles.

**Connect configured accounts** opens the configured sessions concurrently.
Individual controls operate on one profile; failures clear only its snapshots.
Connected profiles refresh every five seconds while this page is visible and stay
connected when navigating elsewhere. Leaving the page stops its automatic reads.
Connections, balances and snapshots are never persisted to the browser or combined
across currencies/accounts. Additional profiles use read-only SDK owners; no broker
write operation is exposed by the profile endpoints.

MTR reuses the primary dashboard owner. Disconnecting MTR also stops that primary
capture session, as the existing Stop & disconnect button does. Selecting another
account in the legacy primary workspace makes the configured MTR card unavailable
until the intended account is selected again. Other profile connections are separate.
The application closes every owned session at shutdown.

API routes use the existing same-origin session authentication:
- GET /api/broker-profiles: safe profile identity and separate snapshots.
- POST /api/broker-profiles/action: {"profile":"GTR","action":"connect"}; actions
  are connect, refresh and disconnect only. The response includes current states;
  check the selected profile's connection/error fields for success.

The capture route and its single destination are unchanged. This release establishes
simultaneous broker connections and separated account views; it does not automatically
copy one signal to five accounts. Logging remains observational.

## Validation

The full Python suite passed 302 tests, followed by 15 targeted profile/server
checks after adding the final authentication test. The frontend suite passed 40
tests. All ten browser scenarios passed across the initial run and the corrected
native-client logging test rerun. Concurrent fake brokers deliberately reused
account and order IDs to verify separation and one-profile failure/disconnect.
No live broker connection or order was initiated to validate this release.
