# Yeet

A set of scripts for managing SSH keys with Bitwarden.

## Installation

1. Install the Bitwarden CLI.
2. Log in to Bitwarden and unlock your vault.

## Usage

### `list`

Lists all SSH keys stored in your Bitwarden vault.

```
./yeet.sh list
```

### `get <key-name>`

Retrieves the specified SSH key from Bitwarden and saves it to `~/.ssh/<key-name>`.

```
./yeet.sh get my-server-key
```

### `create`

Creates a new SSH key, saves it to `~/.ssh/<hostname>-<date>`, and uploads it to Bitwarden.

```
./yeet.sh create
```

### `copy <source-key-path> <new-key-name>`

Uploads an existing local key to Bitwarden with a new name.

```
./yeet.sh copy ~/.ssh/id_rsa my-personal-key
```
