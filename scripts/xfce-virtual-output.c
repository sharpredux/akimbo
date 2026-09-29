/* Tell GTK/XFCE about an active software CRTC on a disconnected connector.
 * Only processes started with this shim and AKIMBO_VIRTUAL_OUTPUT are affected.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <X11/extensions/Xrandr.h>

XRROutputInfo *
XRRGetOutputInfo(Display *display, XRRScreenResources *resources, RROutput output)
{
    static XRROutputInfo *(*original)(Display *, XRRScreenResources *, RROutput);
    XRROutputInfo *info;
    const char *virtual_output;

    if (!original)
        original = dlsym(RTLD_NEXT, "XRRGetOutputInfo");
    if (!original)
        return NULL;

    info = original(display, resources, output);
    virtual_output = getenv("AKIMBO_VIRTUAL_OUTPUT");
    if (info && virtual_output && info->connection == RR_Disconnected && info->crtc &&
        strlen(virtual_output) == (size_t) info->nameLen &&
        memcmp(virtual_output, info->name, info->nameLen) == 0)
        info->connection = RR_Connected;
    return info;
}
