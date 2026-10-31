#pragma once

bool networkBegin(const char *defaultHostname);
void networkTick();
void networkRequestSetup();  // Safe to call from the HTTP server task.
const char *networkHostname();