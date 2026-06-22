# Privacy Policy for HomeBase

**Last updated:** June 22, 2026

## Overview

HomeBase is a Discord bot designed to help households and roommates manage shared expenses, chores, groceries, and other communal activities. This privacy policy explains how we collect, store, and protect your information.

## Data Collection

HomeBase collects the following information only when you actively use the bot:

- **Discord user information:** Your Discord user ID, username, and avatar (for display purposes).
- **Financial data:** Expenses, payments, bills, and account balances you record.
- **Chore assignments:** Chore schedules, completions, and associated members.
- **Household inventory:** Grocery lists, shopping history, and meal voting preferences.
- **House configuration:** House/server name, member roster, wiki entries, birthdays, vacation status, subscription details, and calendar events.
- **Transactional records:** Payment history, settlement records, and audit logs.
- **Optional content:** Quotes, suggestions, milestones, and other user-generated data you choose to store.

HomeBase does **not** collect:
- Payment method information (Discord handles payments; HomeBase only tracks transfers between members).
- Passwords or credentials for external services, unless you explicitly encrypt them using the optional `SUBSCRIPTION_KEY` feature.
- Messages outside of the `/` commands you invoke.
- Location data or device information.

## Data Storage

All data is stored in a **local SQLite database** on the machine where HomeBase runs:

- **Self-hosted:** If you run HomeBase yourself, all data remains on your hardware.
- **Hosting provider:** If hosted on a server (e.g., Oracle Cloud), data is stored on that infrastructure.
- **Encryption:** Subscription passwords are optionally encrypted using Fernet encryption if you provide a `SUBSCRIPTION_KEY`.

HomeBase does **not** send your data to any cloud service, backend server, or third party unless you explicitly authorize it.

## Data Usage

Your data is used exclusively for:

1. Displaying household information (balances, chores, groceries, etc.) to authorized members.
2. Calculating splits, rotations, and summaries for features you use.
3. Sending automated reminders and scheduled posts to your Discord server.
4. Maintaining audit trails for financial and operational transparency.

## Data Retention

Data is retained for as long as the house exists in HomeBase. You can permanently delete all data for a house using the `/delete-house` command (admin-only), which removes:

- All expenses, payments, and settlements.
- All chores, schedules, and history.
- All groceries and shopping records.
- All bills, subscriptions, events, milestones, quotes, and suggestions.
- All member records and house configuration.

Individual members can leave a house, but their historical data (expenses they incurred, chores they completed) is preserved for financial and operational accuracy.

## User Rights

You have the right to:

- **Access:** View all data the bot has collected about you and your house via the bot's commands (`/ledger`, `/balances`, `/chores`, etc.).
- **Delete:** Permanently delete your house and all associated data using `/delete-house`.
- **Correct:** Update your information (birthdays, vacation status, etc.) using the appropriate commands.
- **Withdraw:** Leave a house using `/leave-house`, though historical data involving you remains.

## Third-Party Services

HomeBase integrates with:

- **Discord:** The bot operates through Discord's platform. Discord's [Privacy Policy](https://discord.com/privacy) applies to your Discord account, messages, and server membership.

HomeBase does **not** integrate with:
- Analytics services.
- Advertising networks.
- Payment processors (member-to-member tracking only).
- Backup or cloud storage services.

## Security

- **Local storage:** If self-hosted, you control server security.
- **Encryption:** Optional subscription password encryption via Fernet.
- **Access control:** Only members of your Discord house can see house data.
- **No logging to third parties:** All logs are local to your database.

HomeBase has **no authentication mechanism beyond Discord membership**; all access is tied to your Discord account and the servers you belong to.

## Changes to This Policy

If this privacy policy is updated, the change date will be reflected at the top of this document. Continued use of HomeBase constitutes acceptance of the updated policy.

## Contact

For privacy questions or concerns, contact the bot maintainer. If HomeBase is self-hosted, contact the person who manages your instance.

---

## Summary

**HomeBase is designed for privacy by default:**

- Your data stays local and is not sent to third parties.
- You control when data is stored and can delete it anytime.
- The bot is transparent about what it collects and why.
- No advertising, no tracking, no unauthorized sharing.