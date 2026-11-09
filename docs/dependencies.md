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
for your distribution. The wizard and restore tool run this check automatically
and stop before writing if anything is missing. It does not install anything or
change the system.

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
sudo pacman -Sy --needed clang lld llvm python udisks2 util-linux
```

## Other common distributions

- Linux Mint, Pop!_OS, and Zorin OS use the Ubuntu/Debian `apt` commands.
- EndeavourOS and Garuda use the Arch `pacman --needed` commands.
- Nobara uses the Fedora `dnf` commands.
- openSUSE uses:

  ```sh
  sudo zypper install clang lld llvm python3 udisks2 util-linux
  ```

## SteamOS and other immutable systems

Do not install packages directly on SteamOS or Bazzite. Use an Ubuntu
Distrobox container and run the Ubuntu `apt` commands inside that container.
Avoid changing the host's read-only system image or using `steamos-readonly`
just to run this tool.

Review package names with your administrator before installation. No script in
this repository silently installs packages or uses sudo automatically.
