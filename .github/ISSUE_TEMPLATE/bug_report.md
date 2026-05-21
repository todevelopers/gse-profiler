---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

## Environment
 
|  |  |
|---|---|
| **GNOME version** | |
| **GSE Profiler version** | |
| **Distribution** | |

## Affected component

- [ ] GTK4 application (the desktop UI)
- [ ] Bridge extension (GJS, runs inside gnome-shell)
- [ ] Both / unsure

## Description
 
<!-- What happened? What did you expect? -->
 
## Steps to reproduce
 
<!-- How can I reproduce exact behavior? -->

1. 
2. 
3. 

## Logs

<!-- Include logs relevant to the affected component. -->

**GTK4 app logs** — launch from a terminal and paste stdout/stderr:
```
python3 -m app.main
```

**Bridge extension logs** — run either of these and reproduce the issue:
```
journalctl /usr/bin/gnome-shell -f
```
or open Looking Glass (`Alt+F2 → lg`) and check the **Errors** tab.

```

```
 
## Checklist
 
- [ ] I searched existing issues and found no duplicate
- [ ] GSE Profiler is updated to the latest version
