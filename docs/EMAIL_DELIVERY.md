# Email delivery (REMOVED)

Email OTP and login email delivery were **permanently removed** from PFAI.

- Owner authentication is **username + password + HttpOnly session cookie** (plus optional `X-Owner-Secret` for API clients).
- No SMTP / Resend / SendGrid / mock email providers are used for login.
- Do not set `PFAI_OWNER_EMAIL`, `PFAI_EMAIL_*`, `PFAI_SMTP_*`, or `PFAI_OTP_*` for authentication.
- Status endpoint `/platform/email/status` reports `EMAIL_DELIVERY_STATUS=REMOVED`.

See `docs/OWNER_AUTH.md`.
