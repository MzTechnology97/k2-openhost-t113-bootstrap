#!/bin/sh
# K2-OpenHost slot B: USB0 is the gadget link to the external host. The stock
# "restart" reads usbc0/usb_host, which switches USB0 back to host mode and
# drops the Main/Nozzle/RS-485 channels, so this script does nothing here.
# Cameras connect to the external host.
logger -t k2openhost "chamber_cam_power.sh $* ignored (USB0 is in gadget mode)"
exit 0
