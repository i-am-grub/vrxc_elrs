# RotorHazard VRx Control for the ExpressLRS Backpack

This is a plugin being developed for the RotorHazard timing system with the following features: 
- [X] Send OSD messages to pilots using compatible equipment (such as the [HDZero goggles](https://www.youtube.com/watch?v=VXwaUoA16jc)) 
- [X] Allows for the race manager to [start the race from their transmitter](https://github.com/i-am-grub/VRxC_ELRS?tab=readme-ov-file#control-the-race-from-the-race-directors-transmitter)
- [ ] Pilot's `ready` status from their transmitter

See [here](https://github.com/i-am-grub/VRxC_ELRS/issues/5) for the plugin's current roadmap

## How does it work?

This plugin is built to control to an external device or chip running the ExpressLRS Timer backpack over a serial port. This allows the
timing system to communicate with other devices with an ELRS backpack built into them giving the timer the ability to receive state messages
from a pilot's transmitter, or send messages to display OSD information directly to a pilot's goggles.

## I'm a pilot. What do I need to setup?

Currently, the only device supported for receiving OSD race messages from the ELRS backpack is the HDZero goggles. They come with
an internal ESP32 chip installed for the ExpressLRS backpack. Update the goggles's video receiver backpack to the latest version by either using the
[ExpressLRS Configurator](https://github.com/ExpressLRS/ExpressLRS-Configurator/releases) or the 
[ExpressLRS Web Flasher](https://expresslrs.github.io/web-flasher/). Follow [this guide](https://www.expresslrs.org/hardware/backpack/hdzero-goggles/) for
the first time installation process. If assistance is needed with the installation or upgrading the goggle firmware, 
ask for help in the `help-and-support` channels of the [ExpressLRS Discord](https://discord.gg/expresslrs).

> [!IMPORTANT]
> REMEMBER YOUR BACKPACK BIND PHRASE: The timer's backpack will use it to send OSD messages from the timer to your HDZero goggles.
> You will likely need to provide the bind phrase to the race director if you want OSD information at your race.

> [!NOTE]
> The backpack bind phrase can either be the same or different than the bind phrase used for the ExpressLRS radio protocol. 
> Setting the same bind phrase will not cause the backpack to interfere with the radio protocol.

## Setup Directions for Race Directors

### Installing the Timer Backpack

The list below is of some of the known compatible devices for the RotorHazard Timer Backpack. It is recommended to use a chip that is capable of connecting an external WIFI antenna to
help improve the range of the timer's backpack.

| ELRS Device           | Compatible Hardware                                                                                                   |
| --------------------- | --------------------------------------------------------------------------------------------------------------------- |
| EP82 Module (DIY)     | [ESP8266 NodeMCU](https://a.co/d/9vgX3Tx)                                                                             |
| EP32 Module (DIY)     | [ESP32-DevKitC](https://a.co/d/62OGBgG)                                                                               |
| EP32C3 Module (DIY)   | [ESP32-C3-DevKitM-1U](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-C3-DEVKITM-1U/15198974)      |
| EP32S3 Module (DIY)   | [ESP32-S3-DevKitC-1U](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-S3-DEVKITC-1U-N8R8/16162636) |
| NuclearHazard         | [NuclearHazard Board](https://www.etsy.com/listing/1428199972/nuclearhazard-core-kit-case-and-rx-sold) v7 or newer    |
| [ELRS-Netpack](https://github.com/i-am-grub/elrs-netpack) (DIY) | [Waveshare ESP32-S3 Ethernet](https://www.waveshare.com/esp32-s3-eth.htm)   |

> [!TIP]
> While other specific development boards with similar chipsets may be supported by the targets in the table, it is not guaranteed that they work.
> For example, the Seeed Studio XIAO ESP32C3/S3 board do not work with the targets listed above, but when using the 
> [ExpressLRS Toolchain](https://www.expresslrs.org/software/toolchain-install/) for building the backpack firmware,
> the platformio settings can be changed to build compatible firmware for XIAO boards.

> [!NOTE]
> While a normal ExpressLRS reciever can be flashed with backpack firmware and be used for the timer backpack, this is not recommended.
> The primary reason behind this is that the ELRS backpack is based on ESPNow which uses the WIFI hardware of the ESP32/ESP82.
> Recievers typically have a small ceramic antenna installed seperately for connecting to the web UI over WIFI; this antenna is
> different than the the one(s) reserved for the radio protocol. The ceramic antennta would likely be less performant over an ESP32 
> devkit with an external WIFI antenna connected.

#### Flashing ESP32/ESP82 Devkits

To build and flash the firmware, use the [ExpressLRS Configurator](https://github.com/ExpressLRS/ExpressLRS-Configurator/releases) or the [ExpressLRS Web Flasher](https://expresslrs.github.io/web-flasher/)
1. Connect the device to the computer over USB.

> If Windows doesn't recognize the device connected over USB, a driver install or update may be required.
> Espressif designed boards typically either use the [CP210x](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) or
> [FTDI](https://ftdichip.com/drivers/vcp-drivers/) USB to serial converter chips

2. Select the backpack firmware mode
    - If using the configurator, select `Backpack` on the left side menu. 
    - If using the Web Flasher, select `Race Timer` under the Backpack Firmware section 
3. Select the 1.5.0 (or a newer) release 
4. Select the RotorHazard device category
5. Select the target for the device
6. Select the UART flashing method
7. Enter the backpack bind phrase (for race control from the director's transmitter)
8. Select the COM port for the device
9. Build and flash the firmware

#### Flashing NuclearHazard Hardware

To build the firmware, use the [ExpressLRS Configurator](https://github.com/ExpressLRS/ExpressLRS-Configurator/release) or the [ExpressLRS Web Flasher](https://expresslrs.github.io/web-flasher/)

1. Select the backpack firmware section
   - If using the configurator, select `Backpack` on the left side menu. 
   - If using the Web Flasher, select `Race Timer` under the Backpack Firmware section 
2. Select the 1.5.0 release (or a newer version) 
3. Select the RotorHazard device category
4. Select NuclearHazard as the device
5. Select the method
    - If using the configurator, select `WIFI`. 
    - If using the Web Flasher, select `Local Download` 
6. Enter the backpack bind phrase (for race control from the director's transmitter)
7. Build the firmware
8. Follow [this guide](https://nuclearquads.com/instructions/vrxc) to flash the on board ESP32. Instead of downloading the backpack bin files, use the files built with the configurator.

#### Flashing ELRS Netpack

1. Download the [netpack-installer](https://github.com/i-am-grub/netpack-installer) plugin from the community plugins
list
2. Connect the required ESP32 devkit to your timer
3. In the `ELRS Netpack Firmware` panel (found on the `Settings` page), select the serial port of the connected device
and press the `Flash Netpack Firmware` button.

### Installing the RotorHazard Plugin

1. Verify RotorHazard v4.1.0+ is installed on the timer
2. Follow the instructions in the [latest release](https://github.com/i-am-grub/VRxC_ELRS/releases) of the plugin to complete the installation process.

### Control the Race from the Race Director's Transmitter

There is a feature to control the race from the race director's transmitter by tracking the position of the `DVR Rec` switch setup within the transmitter's backpack. It currently works
by binding the race timer's backpack to the race director's backpack bind phrase similar to the process used with the transmitter and VRx backpacks. 

Currently only starting and stopping the race are supported. Setting up this feature will not prevent other users from receiving OSD messages.

> [!IMPORTANT]
> This feature requires the Race Director to have the ELRS Backpack setup on their transmitter. Please ensure this is setup before completing the following instructions.

1. Setup the `DVR Rec` switch in the ELRS backpack
    1. Open the ExpressLRS Lua script (v3 is recommended) on the transmitter
    2. Open up the Backpack settings
    3. Set the AUX channel for `DVR Rec`

> [!NOTE]
> This will not stop the ability to start recording DVR through this switch. It is just a state that the race timer's backpack listens for.

2. Bind the Race Timer backpack to the Transmitter. This step can be skipped if flashing the timer's backpack with firmware that contains the race director's backpack bind phrase.
    1. Start the RotorHazard server with the ESP32 connected.
    2. Navigate to the `ELRS Backpack General Settings` panel.
    3. Click the `Start Backpack Bind` button.
    4. Within the ExpressLRS Lua script on the transmitter, click `Bind`

To test to see if the backpack was bound successfully, navigate to the `Race` page within RotorHazard, and use the `DVR Rec` switch to start the race. 
[Start Race from Transmitter](https://github.com/i-am-grub/VRxC_ELRS?tab=readme-ov-file#start-race-from-transmitter--checkbox)
or [Stop Race from Transmitter](https://github.com/i-am-grub/VRxC_ELRS?tab=readme-ov-file#stop-race-from-transmitter--checkbox) 
will need to be enabled under `ELRS Backpack General Settings`

> [!TIP]
> Anytime the backpack needs to be bound to a new transmitter, it will be easiest to reflash the ESP32 with the firmware in the latest release, and then rebind.

# Extra Hardware Notes

## 3D Printed Case

Some users have like to use the following 3D printable case available on [Printables](https://www.printables.com/model/762529-esp32-wroom-32u-casing) for
an externally connected `ESP32-DevKitC-1U` board.

![Case](docs/3DPrint/wirex-1.webp)

## WIFI Signal Booster

The quality and reliability of the ExpressLRS backpack is significantly dependent on the HDZero goggle's ability to receive the backpack messages from the timer. Since the
antenna for the goggle's backpack is inside and there may be additional RF interference on the 2.4 GHz with pilot's radio protocols, a WIFI signal booster may help increase
the reliability of the backpack.

My personal setup:
- [ESP32-DevKitC](https://a.co/d/62OGBgG)
- [U.FL to RP-SMA Cables](https://a.co/d/7n99T9o)   
- [800mW Pen Bi-Directional Booster Module](https://www.data-alliance.net/800mw-bi-directional-booster-module-w-rp-sma-female-connectors/)
- [USB Power Cable for powering the booster from the RaspberryPi](https://a.co/d/9iAPV57)
- A high gain 2.4 GHz WIFI antenna with RP-SMA connection

> [!NOTE]
> An ESP32 typically has a maximum power setting less than 100 milliwatts without a signal booster

## USB Extension Cable

[Some groups](https://youtu.be/FZvmfyvRiPE?si=LXu0zXUpDj9NsnUN&t=201) have had good luck with moving the ESP32 closer to the pilots by using a long USB cable or a USB extension cable.

> [!NOTE]
> The RotorHazard development team is looking into setting up the ability to peform a serial-over-https connection. This will allow groups to connect the timer backpack directly to
> the race director's computer instead of the timer. 

# Settings

## Pilot Settings

![Pilot Settings](docs/pilot_atts.png)

### ELRS BP Bindphrase : TEXT

The pilot's individual bind phrase for their backpack. If a bind phrase is not set, the pilot's callsign will be used as a fallback bind phrase instead.

### Enable ELRS OSD : CHECKBOX

Turns the pilot's ELRS OSD on/off

## ELRS Backpack General Settings

![General Settings](docs/general_settings.png)

### Start Race from Transmitter : CHECKBOX

Allows the race director to start the race from their transmitter. Please navigate [here](https://github.com/i-am-grub/VRxC_ELRS#control-the-race-from-the-race-directors-transmitter) for binding the backpack.

### Stop Race from Transmitter : CHECKBOX

Allows the race director to stop the race from their transmitter. Please navigate [here](https://github.com/i-am-grub/VRxC_ELRS#control-the-race-from-the-race-directors-transmitter) for binding the backpack.

### Autosave on stop : CHECKBOX

Automatically save the race when stopping from the transmitter

### Backpack Rescan : BUTTON

Triggers the timer to scan the serial devices for a backpack device. Only works if the timer is not already connected to a backpack device

### Start Backpack Bind : BUTTON

Puts the timer's backpack into a binding mode for pairing with the race director's transmitter.

> [!TIP]
> After successfully completing this process, the timer's backpack will inherit the race director's bind phrase from the transmitter.

### Test Bound Backpack's OSD : BUTTON

Will display OSD messages on HDZero goggles with a matching bind phrase. Used for testing if the timer's backpack successfully inherited the transmitter's bind phrase.

### Start Backpack WIFI : BUTTON

Starts the backpack's WIFI mode. Used for over-the-air firmware updates. 

> [!TIP]
> To connect to the backpack's web user interface, verify the backpack is setup to connect to the same network as the device used to access the web user interface,
> or connect the device to the wireless network the backpack created. Open `http://elrs_timer.local` in the device's browser to connect to the web user interface.

## ELRS Backpack OSD Settings

![OSD Settings](docs/osd_settings.png)

> [!NOTE]
> It is a goal of this project to eventually move all the OSD settings in this section to be pilot configurable through the ExpressLRS VRx backpack's web user interface.
> The current implementation is noted to be a work around until enough progress has been completed on the VRx backpack for individual pilot configuration.

### Show Heat Name : CHECKBOX

Shows the race's heat name to pilots when active

### Show Round Number : CHECKBOX

Shows the race's round number to pilots when active. Also requires `Show Heat Name` to be active.

### Show Class Name : CHECKBOX

Shows the race's class name to pilots when active

### Show Event Name : CHECKBOX

Shows the race's event name to pilots when active

### Show Current Position and Lap : CHECKBOX

- TOGGLED ON: Shows current position and current lap when multiple pilots are in a race
- TOGGLED OFF: Only shows current lap

### Show Gap Time : CHECKBOX

- TOGGLED ON: Shows the gap time to next pilot if using a compatible win condition for the race
- TOGGLED OFF: Shows lap result time

### Show Post-Race Results : CHECKBOX

The pilot will be shown results when they finish the race. It is recommended to have pilots turn off `Post Flight Results` in Betaflight so the results won't be overridden when the pilot lands.

### Race Stage Message : TEXT

The message shown to pilots when the timer is staging the race

### Race Start Message : TEXT

The message shown to pilots when the race first starts

### Pilot Done Message : TEXT

The message shown to pilots when the pilot finishes

### Race Finish Message : TEXT

The message shown to pilots when the time runs out

### Race Stop Message : TEXT

The message shown to pilots when the race is stopped

### Race Leader Message : TEXT

The message shown to pilots when `Show Gap Time` is enabled and the pilot is leading the race

### Start Message Uptime : INT

The length of time `Race Start Message` is shown to pilots

### Finish Message Uptime : INT

The length of time `Pilot Done Message` and `Race Finish Message` is shown to pilots

### Lap Result Uptime : INT

Length of time the pilot's lap or gap time is shown after completing a lap. 

### Announcement Uptime : INT

Length of time to show announcements to pilots. (e.g. When a race is scheduled)

### Heat Name Row : INT

Row to show the heat name on when the race is staging.

### Class Name Row : INT

Row to show the class name on when the race is staging.

### Event Name Row : INT

Row to show the event name on when the race is staging.

### Announcement Row : INT

Row to show announcements such as when a race is scheduled. This row is also used by `Show Race Name on Stage`

### Race Status Row : INT

Row to show race status messages.

### Current Lap/Position Row : INT

Row to show current lap and position

### Lap/Gap Results Row : INT

Row to show lap or gap time

### Results Rows : INT

The row to start showing a pilot's post race statistics on. It will also use the follow row in conjunction with the entered one.
