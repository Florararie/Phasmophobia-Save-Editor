# Phasmophobia-Save-Editor
Just a simple script to decrypt Phasmophobia save files to readable JSON which you can then edit and re-encrypt for use.

## Requirements

```
pip install pycryptodome
```

## Save File locatons

On Windows, save data can be located at `%appdata%\..\LocalLow\Kinetic Games\Phasmophobia\SaveFile.txt`

On Linux (Proton), save data can be located at `~/.steam/steam/steamapps/compatdata/739630/pfx/drive_c/users/steamuser/AppData/LocalLow/Kinetic Games/SaveFile.txt`

> Desc from https://phasmoeditor.cnnd.dev/

## Example Usage

```python
if __name__ == "__main__":
    es3 = EasySave3("t36gref9u84y7f43g") # <-- Phasmophobia Password
    es3.decrypt_to_json("SaveFile.txt", "SaveFile.readable.json")
```

Encrypt again after any edits

```python
if __name__ == "__main__":
    es3 = EasySave3("t36gref9u84y7f43g") # <-- Phasmophobia Password
    es3.encrypt_from_json("SaveFile.readable.json", "SaveFile.encrypted.txt")
```

I'm too lazy to develop past this point as I only made this for a few simple edits. So nothing fancy like a GUI will be made (but feel free to fork and add yourself if you'd like)  

Some fields to note-

- PlayersMoney : Self explanatory. The player's money.
- NewLevel : Player's current level
- Experience : How much experience you currently have, can add to make progress to next level quicker
- \<ItemType>TierThreeUnlockOwned : Whether or not you own tier three of that item. Can set to `true` to unlock them automatically
- Bone<1-12> : Can set each of these entries to `3` to make them appear in the cabinet in the main lobby  

</br>

That's all I cared to check. Of course other things can be changed, but do so at your own discretion.

> Made with <3 by Flory
