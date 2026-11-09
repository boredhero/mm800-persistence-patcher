# Dependencies

You do not need Pipenv or a virtual environment. All host tools use Python's
standard library. Use your operating system's package manager for the compiler
and Linux utilities.

## Check first

From the repository directory:

```sh
python3 tools/check_dependencies.py
```

It lists available and missing commands and prints a suggested install command
for your distribution. It does not install anything or change the system.

## Debian and Ubuntu

```sh
sudo apt update
sudo apt install clang lld llvm python3 udisks2 util-linux
```

- `clang` and `lld`: compiler and linker
- `llvm`: `llvm-objcopy` and `llvm-nm`
- `python3`: host tools
- `udisks2`: `udisksctl` for mounting the recovery drive
- `util-linux`: `lsblk` and `findmnt`

## Fedora

```sh
sudo dnf install clang lld llvm python3 udisks2 util-linux
```

## Arch Linux and Manjaro

```sh
sudo pacman -S --needed clang lld llvm python udisks2 util-linux
```

Review package names with your administrator before installation. No script in
this repository silently installs packages or uses sudo automatically.
