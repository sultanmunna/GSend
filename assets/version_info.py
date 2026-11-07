# Windows version resource for GmailNotifier.exe (consumed by PyInstaller
# --version-file). Keep ProductVersion in sync with pyproject.toml.
# The VSVersionInfo names below are injected by PyInstaller when it parses
# this file, so the linter cannot see them.
# ruff: noqa: F821
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(0, 1, 0, 0),
        prodvers=(0, 1, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Gmail Tray Notifier"),
                        StringStruct("FileDescription", "Gmail Tray Notifier"),
                        StringStruct("FileVersion", "0.1.0"),
                        StringStruct("InternalName", "GmailNotifier"),
                        StringStruct("LegalCopyright", ""),
                        StringStruct("OriginalFilename", "GmailNotifier.exe"),
                        StringStruct("ProductName", "Gmail Tray Notifier"),
                        StringStruct("ProductVersion", "0.1.0"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
