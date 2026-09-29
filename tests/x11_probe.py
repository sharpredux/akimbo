"""Create one temporary managed window and verify off-screen rendering."""
import ctypes as c
import time


def probe(plan):
    x = c.CDLL('libX11.so.6')
    pointer, window = c.c_void_p, c.c_ulong
    signatures = {
        'XOpenDisplay': ([c.c_char_p], pointer),
        'XDefaultRootWindow': ([pointer], window),
        'XCreateSimpleWindow': ([pointer, window, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_uint, c.c_ulong, c.c_ulong], window),
        'XStoreName': ([pointer, window, c.c_char_p], c.c_int),
        'XMapWindow': ([pointer, window], c.c_int),
        'XMoveWindow': ([pointer, window, c.c_int, c.c_int], c.c_int),
        'XClearWindow': ([pointer, window], c.c_int),
        'XSync': ([pointer, c.c_int], c.c_int),
        'XTranslateCoordinates': ([pointer, window, window, c.c_int, c.c_int, c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(window)], c.c_int),
        'XGetImage': ([pointer, window, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_ulong, c.c_int], pointer),
        'XGetPixel': ([pointer, c.c_int, c.c_int], c.c_ulong),
        'XDestroyImage': ([pointer], c.c_int),
        'XDestroyWindow': ([pointer, window], c.c_int),
        'XCloseDisplay': ([pointer], c.c_int),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(x, name); fn.argtypes = args; fn.restype = result
    display = x.XOpenDisplay(None)
    if not display: raise RuntimeError('Cannot connect to X11')
    root = x.XDefaultRootWindow(display)
    color = 0x3A8F66
    win = x.XCreateSimpleWindow(display, root, 100, 100, 200, 120, 0, 0, color)
    try:
        x.XStoreName(display, win, b'Akimbo temporary rendering test')
        x.XMapWindow(display, win); x.XSync(display, 0)
        time.sleep(0.4)
        x.XMoveWindow(display, win, plan['x'] + 100, plan['y'] + 100)
        x.XClearWindow(display, win); x.XSync(display, 0)
        time.sleep(0.4)
        px, py, child = c.c_int(), c.c_int(), window()
        x.XTranslateCoordinates(display, win, root, 60, 60, c.byref(px), c.byref(py), c.byref(child))
        assert plan['x'] <= px.value < plan['x'] + plan['w'], px.value
        assert plan['y'] <= py.value < plan['y'] + plan['h'], py.value
        image = x.XGetImage(display, root, px.value, py.value, 1, 1, c.c_ulong(-1), 2)
        if not image: raise RuntimeError('Cannot capture the virtual desktop pixel')
        try: assert x.XGetPixel(image, 0, 0) & 0xFFFFFF == color, 'Virtual region did not render the expected pixel'
        finally: x.XDestroyImage(image)
        print('XFCE managed window moved into the virtual monitor; captured pixel matches.')
    finally:
        x.XDestroyWindow(display, win); x.XSync(display, 0); x.XCloseDisplay(display)


def probe_pointer(plan):
    """Briefly warp into the virtual CRTC, then return to the original position."""
    x = c.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes = [c.c_char_p]; x.XOpenDisplay.restype = c.c_void_p
    x.XDefaultRootWindow.argtypes = [c.c_void_p]; x.XDefaultRootWindow.restype = c.c_ulong
    x.XQueryPointer.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_ulong),
                                c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_int),
                                c.POINTER(c.c_int), c.POINTER(c.c_uint)]
    x.XWarpPointer.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_int, c.c_int,
                               c.c_uint, c.c_uint, c.c_int, c.c_int]
    x.XSync.argtypes = [c.c_void_p, c.c_int]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    display = x.XOpenDisplay(None)
    if not display: raise RuntimeError('Cannot connect to X11')
    root = x.XDefaultRootWindow(display)
    def position():
        rw, child = c.c_ulong(), c.c_ulong()
        rx, ry, wx, wy, mask = c.c_int(), c.c_int(), c.c_int(), c.c_int(), c.c_uint()
        x.XQueryPointer(display, root, c.byref(rw), c.byref(child), c.byref(rx), c.byref(ry),
                        c.byref(wx), c.byref(wy), c.byref(mask))
        return rx.value, ry.value
    original = position()
    target = (plan['x'] + plan['w'] // 2, plan['y'] + plan['h'] // 2)
    try:
        x.XWarpPointer(display, 0, root, 0, 0, 0, 0, *target)
        x.XSync(display, 0)
        reached = position()
    finally:
        x.XWarpPointer(display, 0, root, 0, 0, 0, 0, *original)
        x.XSync(display, 0)
        x.XCloseDisplay(display)
    assert reached == target, f'Pointer clipped at {reached}; wanted {target}'
    print('X11 pointer reached virtual monitor center and was restored.')


def probe_drag(plan):
    """Drag a temporary managed title bar across the laptop/iPad boundary."""
    x = c.CDLL('libX11.so.6')
    xtest = c.CDLL('libXtst.so.6')
    pointer, window = c.c_void_p, c.c_ulong
    signatures = {
        'XOpenDisplay': ([c.c_char_p], pointer),
        'XDefaultRootWindow': ([pointer], window),
        'XCreateSimpleWindow': ([pointer, window, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_uint, window, window], window),
        'XStoreName': ([pointer, window, c.c_char_p], c.c_int),
        'XMapWindow': ([pointer, window], c.c_int),
        'XSync': ([pointer, c.c_int], c.c_int),
        'XTranslateCoordinates': ([pointer, window, window, c.c_int, c.c_int, c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(window)], c.c_int),
        'XQueryPointer': ([pointer, window, c.POINTER(window), c.POINTER(window), c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_uint)], c.c_int),
        'XDestroyWindow': ([pointer, window], c.c_int),
        'XCloseDisplay': ([pointer], c.c_int),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(x, name); fn.argtypes = args; fn.restype = result
    xtest.XTestFakeMotionEvent.argtypes = [pointer, c.c_int, c.c_int, c.c_int, window]
    xtest.XTestFakeButtonEvent.argtypes = [pointer, c.c_uint, c.c_int, window]
    display = x.XOpenDisplay(None)
    if not display: raise RuntimeError('Cannot connect to X11')
    root = x.XDefaultRootWindow(display)
    rw, child = window(), window()
    rx, ry, wx, wy, mask = c.c_int(), c.c_int(), c.c_int(), c.c_int(), c.c_uint()
    x.XQueryPointer(display, root, c.byref(rw), c.byref(child), c.byref(rx), c.byref(ry),
                    c.byref(wx), c.byref(wy), c.byref(mask))
    previous_pointer = (rx.value, ry.value)
    win = x.XCreateSimpleWindow(display, root, 400, 240, 320, 200, 0, 0, 0x7AAAC2)
    try:
        x.XStoreName(display, win, b'Akimbo temporary drag test')
        x.XMapWindow(display, win); x.XSync(display, 0)
        time.sleep(0.3)
        def origin():
            px, py, child = c.c_int(), c.c_int(), window()
            x.XTranslateCoordinates(display, win, root, 0, 0, c.byref(px), c.byref(py), c.byref(child))
            return px.value, py.value
        before = origin()
        start_x, start_y = before[0] + 100, before[1] - 12
        xtest.XTestFakeMotionEvent(display, -1, start_x, start_y, 0)
        x.XSync(display, 0)
        xtest.XTestFakeButtonEvent(display, 1, 1, 0)
        x.XSync(display, 0)
        time.sleep(0.2)
        for y in range(start_y + 100, plan['y'] + plan['h'] // 2, 100):
            xtest.XTestFakeMotionEvent(display, -1, start_x, y, 0)
            x.XSync(display, 0)
            time.sleep(0.025)
        xtest.XTestFakeButtonEvent(display, 1, 0, 0)
        x.XSync(display, 0)
        time.sleep(0.2)
        after = origin()
        assert after[1] > plan['y'] + 50, f'Title-bar drag stopped at {after}'
        print(f'XFCE title-bar drag crossed into iPad monitor: y={after[1]}.')
    finally:
        xtest.XTestFakeButtonEvent(display, 1, 0, 0)
        xtest.XTestFakeMotionEvent(display, -1, *previous_pointer, 0)
        x.XDestroyWindow(display, win)
        x.XSync(display, 0)
        x.XCloseDisplay(display)
