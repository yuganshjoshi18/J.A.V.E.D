# Repository storage folders

These folders document the intended on-disk layout from the project brief, but
J.A.V.E.D. deliberately keeps all mutable data **outside the repository**:

```
%LOCALAPPDATA%\JAVED\
├── config\settings.json
├── database\javed.db
├── reports\
├── documents\
├── exports\
├── logs\javed.log
└── secrets\gemini_api_key.bin   (DPAPI-encrypted)
```

Reason: GitHub uploads must never contain credentials, private databases, logs
or user documents, and OneDrive sync should not capture secrets. Do not add
runtime files to these folders for upload.

Set `JAVED_DATA_DIR` to relocate the data root for portable or test installs.
