# Submitter naming, retain `user_t` table

The legacy database table `user_t` represents people who submit samples for dating, not software-login users. We name this concept **Submitter** in Python classes, routes, viewmodels, templates, and magic-nav, but keep the DB table name `user_t` to avoid migrating a live MySQL database. "User" is reserved for a future authentication concept. "Client" was rejected because many submitters are non-paying academic researchers for whom that framing feels off.
