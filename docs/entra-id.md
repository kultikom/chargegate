# Microsoft Entra ID

Entra ID is optional. Employees and tags can always be managed manually in the UI, and both
ways can be mixed.

## Employee sync

Members of one Entra group (nested groups included) become employees in ChargeGate.

| Situation in Entra | Result in ChargeGate |
|---|---|
| member of the group, account enabled | employee active |
| removed from the group or account disabled | employee deactivated, tags stop working |
| tag UID in the configured attribute | tag created/updated (source "entra") |

Tags assigned manually in the UI are never touched by the sync – only tags that came from Entra
are reconciled. After each sync the tag list on the stations is updated.

### Setup

1. **Entra admin center › App registrations › New registration**, e.g. "ChargeGate"
2. **Certificates & secrets** › new client secret
3. **API permissions** › Microsoft Graph › **Application permissions**:
   `User.Read.All`, `GroupMember.Read.All` › **Grant admin consent**
4. Create a security group, e.g. "EV charging", and add the employees
5. Store each employee's tag UID in `extensionAttribute10` (several tags separated by commas).
   You can choose another attribute with `entra_rfid_attribute` / `ENTRA_RFID_ATTRIBUTE`;
   top-level attributes like `employeeId` work too.
6. Enter tenant ID, client ID, client secret and the group's object ID in ChargeGate

Setting `extensionAttribute10` for a cloud-only user, e.g. with Microsoft Graph PowerShell:

```powershell
Update-MgUser -UserId anna@example.com -OnPremisesExtensionAttributes @{ extensionAttribute10 = "04A2B3C4" }
```

For users synced from on-premises AD, set the attribute in AD instead.

## Admin sign-in with Microsoft (standalone only)

In the Home Assistant app, Home Assistant handles sign-in. In the standalone version you can let
admins sign in with Microsoft:

1. Same app registration, **Authentication** › add platform **Web**, redirect URI
   `https://<your-chargegate-url>/auth/callback` (HTTPS required)
2. Set `ENTRA_REDIRECT_URI` to that URL
3. Allow admins via `ADMIN_EMAILS` (comma-separated) and/or `ADMIN_GROUP_ID`
   (requires the *groups* claim in the token configuration)
