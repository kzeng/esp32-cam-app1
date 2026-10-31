#pragma once
// Copy this file to secrets.h, then edit locally. Never commit secrets.h.
// Wi-Fi credentials are entered through the setup hotspot and saved in NVS.
// Optional: unique lowercase LAN hostname, without .local (default: pet-camera).
#define CAMERA_HOSTNAME "pet-camera"
// Generate a random hex key; use the same value in gateway/.env CAMERA_KEY.
#define CAMERA_KEY "CHANGE_TO_A_RANDOM_KEY_AT_LEAST_32_CHARACTERS"
