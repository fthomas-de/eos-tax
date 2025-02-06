# eostax settings
local.py

```
TAX_ALLIANCES = [99003995]
CURRENT_MONTH = True
LAST_MONTH = True
TAX_RATE = 0.1
TAX_TYPES = ['bounty_prizes']
USE_REASON = False
TAX_CORPORATIONS = [98399796]
```

If the alliance ID is not yet loaded, go to:
http://127.0.0.1:8000/admin/eveonline/eveallianceinfo/ and add the alliance on the top right.


## Features

## How to use it

## Installing into production AA
pip install git+https://github.com/fthomas-de/eos-tax


Then add `eos_tax',` to `INSTALLED_APPS` in `settings/local.py`, run migrations and restart your allianceserver.