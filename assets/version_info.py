# Windows version resource for GSend.exe (consumed by PyInstaller
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
                        StringStruct("CompanyName", "GSend"),
                        StringStruct("FileDescription", "GSend"),
                        StringStruct("FileVersion", "0.1.0"),
                        StringStruct("InternalName", "GSend"),
                        StringStruct("LegalCopyright", ""),
                        StringStruct("OriginalFilename", "GSend.exe"),
                        StringStruct("ProductName", "GSend"),
                        StringStruct("ProductVersion", "0.1.0"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
