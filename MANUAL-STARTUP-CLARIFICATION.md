# Software startup in the SHRT manuals

Software startup is documented as part of device initialization. It should not be described as an undocumented universal workaround, or an extra step required after every successful commissioning.

## Relevant references

The printed page number differs from the page counted by a PDF viewer. Confirm the edition inside the document; hosted files and filename labels can differ.

| Manufacturer document | Location | Subject |
| --- | --- | --- |
| [SHRT manual, internally labelled Ver20-202212](https://info-support.sungrowpower.com/application/pdf/2023/04/21/SH5.0-10RT-5.0-10RT-20-UEN-Ver21-202302.pdf#page=108) | Section 8.4.2, step 6; printed p. 96 / PDF p. 108 | Finish initialization and use the device-on control; the application sends a start instruction |
| [SHRT manual, Ver24-202503](https://info-support.sungrowpower.com/application/pdf/2025/07/17/SHRT%20User%20Manual.pdf#page=92) | Section 7.2; printed p. 84 / PDF p. 92 | Electrical startup, waiting time and suitable grid/irradiation conditions |
| [SHRT manual, Ver24-202503](https://info-support.sungrowpower.com/application/pdf/2025/07/17/SHRT%20User%20Manual.pdf#page=98) | Section 7.4, step 9; printed p. 90 / PDF p. 98 | Device initialization and protection parameters |
| [SHRT manual, Ver24-202503](https://info-support.sungrowpower.com/application/pdf/2025/07/17/SHRT%20User%20Manual.pdf#page=104) | Section 8.4; printed p. 96 / PDF p. 104 | Reference to the separate iSolarCloud App commissioning guide |

The older download URL contains `Ver21-202302`, although the referenced PDF identifies itself internally as `Ver20-202212`. In that edition, section **8.11.4 Start/Stop Switch** concerns the EV charger, not the inverter startup procedure.

## Diagnostic implications

Electrical startup, application initialization and the current software Start/Stop state are distinct checks. A completed setup screen does not substitute for reading the current state. Conversely, a stopped state alone cannot establish whether an initialization command was omitted, rejected or followed by another action.

The cited passages do not establish that all firmware and WiNet web interfaces implement the same flow. They also do not explain every possible zero-reading or persistent-Stop symptom. Use the manual for the actual model and firmware together with fresh diagnostics.

See [troubleshooting](TROUBLESHOOTING.md) and the [guarded CLI Start procedure](NETWORK-SCRIPTS.md).
