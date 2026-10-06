import bpy, gpu
gpu.init()

def P(*a):
    print("[PROBE]", *a, flush=True)

SHADERS = ['FLAT_COLOR', 'IMAGE', 'IMAGE_SCENE_LINEAR_TO_REC709_SRGB', 'IMAGE_COLOR',
           'IMAGE_COLOR_SCENE_LINEAR_TO_REC709_SRGB', 'SMOOTH_COLOR', 'UNIFORM_COLOR',
           'POLYLINE_FLAT_COLOR', 'POLYLINE_SMOOTH_COLOR', 'POLYLINE_UNIFORM_COLOR',
           'POINT_FLAT_COLOR', 'POINT_UNIFORM_COLOR']

CANDS = ["color", "Color", "image", "Texture", "uv", "texCoord", "viewportSize", "lineWidth",
         "size", "diameter", "alpha", "pixel_size", "outlineWidth", "fillColor", "wireColor",
         "ModelViewProjectionMatrix", "ModelMatrix", "ProjectionMatrix", "ViewMatrix",
         "depthTexture", "mask", "aspect", "smooth", "Smooth", "pointSize"]

P("| shader | attrs | uniforms (name: guessed kind) |")
for name in SHADERS:
    sh = gpu.shader.from_builtin(name)
    attrs = sh.attrs_info_get()
    found = []
    for u in CANDS:
        ok4 = ok1 = okv3 = False
        try:
            sh.uniform_float(u, (1.0, 1.0, 1.0, 1.0)); ok4 = True
        except Exception:
            pass
        if not ok4:
            try:
                sh.uniform_float(u, 1.0); ok1 = True
            except Exception:
                pass
        if not ok4 and not ok1:
            try:
                sh.uniform_float(u, (1.0, 1.0)); okv3 = True
            except Exception:
                pass
        if ok4 or ok1 or okv3:
            kind = "vec4" if ok4 else ("scalar" if ok1 else "vec2")
            found.append("%s(%s)" % (u, kind))
    P("### %-45s attrs=%s" % (name, attrs))
    P("      uniforms: %s" % (", ".join(found) or "NONE (only auto MVP)"))
    P("      internal name: %s" % sh.name)
