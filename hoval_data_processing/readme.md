# Preset generation

The presets in `esphome/components/toptronic/presets/` are generated from the
**official Hoval TopTronic datapoint workbook** (`TTE-GW-Modbus-datapoints.xlsx`).
That workbook is copyrighted by Hoval AG and is **not** committed to this
repository — download it locally first (the Hoval URL is also used by the
`update_datapoints.py` tool):

- Hoval CDN:
  <https://cdn.hoval.com/toptronice-gateway-modbus-datapoints_hybris_original.xlsx>
- Hoval page (Blog "Modbus-Integration" → Downloads):
  <https://www.hoval.com/misc/TTE/TTE-GW-Modbus-datapoints.xlsx>

Save it as `hoval_data_processing/TTE-GW-Modbus-datapoints.xlsx` (gitignored),
then generate:

```bash
python hoval_data_processing/generate_presets.py esphome/components/toptronic/presets
```

## Keeping the datapoint list current

```bash
python hoval_data_processing/update_datapoints.py --check   # report only
python hoval_data_processing/update_datapoints.py --apply   # download + regenerate
```

`--apply` downloads the current workbook, compares its sha256 against
`datapoints_version.json`, and on change regenerates the presets into a
staging area first. Only after generation succeeds and the entity-count
sanity check passes is the previous workbook backed up, the new workbook
installed and the staged presets copied into place -- a failed update leaves
the repository untouched.

