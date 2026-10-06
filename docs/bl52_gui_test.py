"""GUI end-to-end verification of GPU/UI drawing API in Blender 5.2.2.
Run WITHOUT --background so a real SpaceView3D WINDOW draw handler executes.
"""
import sys, os, json, traceback
import bpy
import gpu
import blf
from mathutils import Matrix
from gpu.types import GPUVertFormat, GPUVertBuf, GPUBatch, GPUIndexBuf
from gpu_extras.batch import batch_for_shader

OUT_PATH = r"E:\360MoveData\Users\ASUS\Desktop\deepseek\gui_draw_result.json"

RESULTS = []
STATE = {"frames": 0, "handle": None, "tex": None, "img": None, "quad": None, "texbatch": None, "shader_flat": None, "shader_img": None}


def setup_resources():
    # --- image + texture (item 4/7) ---
    import numpy as np
    img = bpy.data.images.new("probe_atlas", 4, 4, alpha=True, float_buffer=False)
    arr = np.zeros((4, 4, 4), dtype=np.float32)
    arr[..., 3] = 1.0
    arr[0, 0] = (1.0, 0.0, 0.0, 1.0)
    arr[3, 3] = (0.0, 1.0, 0.0, 1.0)
    img.pixels.foreach_set(arr.ravel())
    STATE["img"] = img
    STATE["tex"] = gpu.texture.from_image(img)
    RESULTS.append(("texture_from_image", {"ok": True, "w": STATE["tex"].width, "h": STATE["tex"].height,
                                           "format": STATE["tex"].format}))

    # --- flat color quad (item 1/2/3) ---
    sf = gpu.shader.from_builtin('UNIFORM_COLOR')
    STATE["shader_flat"] = sf
    RESULTS.append(("shader_UNIFORM_COLOR_attrs", list(sf.attrs_info_get())))
    verts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    # vertex format built manually (2D positions)
    fmt = GPUVertFormat()
    pos_id = fmt.attr_add(id="pos", comp_type='F32', len=2, fetch_mode='FLOAT')
    vbo = GPUVertBuf(len=4, format=fmt)
    vbo.attr_fill(id=pos_id, data=verts)
    ibo = GPUIndexBuf(type='TRIS', seq=[(0, 1, 2), (2, 3, 0)])
    STATE["quad"] = GPUBatch(type='TRIS', buf=vbo, elem=ibo)

    # --- textured quad (item 4) ---
    si = gpu.shader.from_builtin('IMAGE')
    STATE["shader_img"] = si
    RESULTS.append(("shader_IMAGE_attrs", list(si.attrs_info_get())))
    uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    STATE["texbatch"] = batch_for_shader(si, 'TRIS', {"pos": uv, "texCoord": uv},
                                       indices=[(0, 1, 2), (2, 3, 0)])
    RESULTS.append(("texbatch_ok", True))
    try:
        si.uniform_sampler("image", STATE["tex"])
        RESULTS.append(("uniform_sampler_image", "OK"))
    except Exception as e:
        RESULTS.append(("uniform_sampler_image", "FAIL: %r" % (e,)))


def draw_callback():
    """WINDOW / POST_PIXEL draw handler on SpaceView3D."""
    STATE["frames"] += 1
    rec = {}
    try:
        ctx = bpy.context
        rec["context_region"] = None if ctx.region is None else (ctx.region.type, ctx.region.width, ctx.region.height)
        rec["context_space_data"] = None if ctx.space_data is None else ctx.space_data.type
        rec["context_area"] = None if ctx.area is None else ctx.area.type
        rec["proj_matrix"] = [list(r) for r in gpu.matrix.get_projection_matrix()]
        rec["modelview"] = [list(r) for r in gpu.matrix.get_model_view_matrix()]
        rec["viewport"] = tuple(gpu.state.viewport_get())
        rec["blend_get"] = gpu.state.blend_get()
        rec["depth_test_get"] = gpu.state.depth_test_get()
    except Exception as e:
        rec["context_err"] = repr(e)
    RESULTS.append(("context_at_draw", rec))

    if STATE["frames"] > 1:
        return

    # 3) exact state + matrix sequence
    try:
        gpu.state.blend_set('ALPHA')
        RESULTS.append(("blend_set_ALPHA", gpu.state.blend_get()))
        gpu.state.depth_test_set('NONE')
        RESULTS.append(("depth_test_set_NONE", gpu.state.depth_test_get()))
        gpu.state.depth_mask_set(False)
        RESULTS.append(("depth_mask_set", "OK"))
        gpu.state.face_culling_set('NONE')
        RESULTS.append(("face_culling_set", "OK"))
    except Exception as e:
        RESULTS.append(("gpu_state_FAIL", repr(e)))

    # gpu.matrix.push / pop
    try:
        gpu.matrix.push()
        gpu.matrix.load_identity()
        RESULTS.append(("load_identity_ok", "OK"))
        gpu.matrix.pop()
        RESULTS.append(("push_pop_ok", "OK"))
    except Exception as e:
        RESULTS.append(("push_pop_FAIL", repr(e)))

    # push_pop context manager
    try:
        with gpu.matrix.push_pop():
            gpu.matrix.translate((10.0, 10.0))
            gpu.matrix.scale((2.0, 2.0))
        RESULTS.append(("push_pop_cm_ok", "OK"))
    except Exception as e:
        RESULTS.append(("push_pop_cm_FAIL", repr(e)))

    # hasattr checks for the matrix API the user asked about
    RESULTS.append(("has_load_orthographic", hasattr(gpu.matrix, "load_orthographic")))
    RESULTS.append(("has_ortho", hasattr(gpu.matrix, "ortho")))
    RESULTS.append(("matrix_api", sorted(n for n in dir(gpu.matrix) if not n.startswith("_"))))

    # explicit ortho projection via mathutils Matrix
    try:
        reg = bpy.context.region
        w, h = (reg.width if reg else 1920), (reg.height if reg else 1080)
        m = Matrix((
            (2.0 / w, 0.0, 0.0, -1.0),
            (0.0, 2.0 / h, 0.0, -1.0),
            (0.0, 0.0, -1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        gpu.matrix.push_projection()
        gpu.matrix.load_projection_matrix(m)
        got = [list(r) for r in gpu.matrix.get_projection_matrix()]
        RESULTS.append(("load_projection_matrix_ortho_ok", got == [list(r) for r in m]))
        gpu.matrix.pop_projection()
        RESULTS.append(("push_pop_projection_ok", "OK"))
    except Exception as e:
        RESULTS.append(("ortho_FAIL", repr(e)))

    # 1+2) draw flat-color quad in pixel coords
    try:
        sf = STATE["shader_flat"]
        with gpu.matrix.push_pop():
            gpu.matrix.translate((100.0, 100.0))
            gpu.matrix.scale((200.0, 150.0))
            sf.uniform_float("color", (1.0, 0.4, 0.1, 0.8))
            STATE["quad"].draw(sf)
        RESULTS.append(("draw_flat_quad_2D_pixels", "OK"))
    except Exception as e:
        RESULTS.append(("draw_flat_quad_2D_pixels", "FAIL: %r" % (e,)))

    # 4) draw textured quad
    try:
        si = STATE["shader_img"]
        with gpu.matrix.push_pop():
            gpu.matrix.translate((400.0, 100.0))
            gpu.matrix.scale((128.0, 128.0))
            si.uniform_sampler("image", STATE["tex"])
            STATE["texbatch"].draw(si)
        RESULTS.append(("draw_textured_quad", "OK"))
    except Exception as e:
        RESULTS.append(("draw_textured_quad", "FAIL: %r" % (e,)))

    # IMAGE_COLOR color tint
    try:
        sic = gpu.shader.from_builtin('IMAGE_COLOR')
        sic.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        f = GPUVertFormat()
        pid = f.attr_add(id="pos", comp_type='F32', len=2, fetch_mode='FLOAT')
        vb = GPUVertBuf(len=4, format=f)
        vb.attr_fill(id=pid, data=[(0, 0), (1, 0), (1, 1), (0, 1)])
        b = GPUBatch(type='TRI_FAN', buf=vb)
        with gpu.matrix.push_pop():
            gpu.matrix.translate((550.0, 100.0))
            gpu.matrix.scale((64.0, 64.0))
            sic.uniform_sampler("image", STATE["tex"])
            b.draw(sic)
        RESULTS.append(("draw_IMAGE_COLOR_tinted", "OK"))
    except Exception as e:
        RESULTS.append(("draw_IMAGE_COLOR_tinted", "FAIL: %r" % (e,)))

    # 5) blf text
    try:
        blf.size(0, 20)
        blf.color(0, 1.0, 1.0, 1.0, 1.0)
        blf.position(0, 50.0, 50.0, 0.0)
        blf.draw(0, "Blender 5.2 blf test")
        RESULTS.append(("blf_draw", "OK"))
        RESULTS.append(("blf_dimensions", tuple(blf.dimensions(0, "Blender 5.2 blf test"))))
    except Exception as e:
        RESULTS.append(("blf_draw", "FAIL: %r" % (e,)))

    # 8) shading readback
    try:
        sd = bpy.context.space_data
        RESULTS.append(("shading_type", sd.shading.type))
        RESULTS.append(("shading_has_color_type", hasattr(sd.shading, "color_type")))
        RESULTS.append(("shading_has_studiolight_background_alpha", hasattr(sd.shading, "studiolight_background_alpha")))
    except Exception as e:
        RESULTS.append(("shading_FAIL", repr(e)))


def finish():
    try:
        if STATE["handle"] is not None:
            bpy.types.SpaceView3D.draw_handler_remove(STATE["handle"], 'WINDOW')
            RESULTS.append(("draw_handler_remove", "OK"))
    except Exception as e:
        RESULTS.append(("draw_handler_remove", "FAIL: %r" % (e,)))
    try:
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(RESULTS, fh, indent=1)
    except Exception as e:
        print("[GUI] write fail", e)
    print("[GUI] wrote", OUT_PATH)
    bpy.ops.wm.quit_blender()


def arm():
    STATE["handle"] = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (), 'WINDOW', 'POST_PIXEL')
    RESULTS.append(("draw_handler_add_ret", str(STATE["handle"])[:80]))
    return None


def main():
    try:
        gpu.init()
        RESULTS.append(("gpu_init_in_gui", "OK"))
    except Exception as e:
        RESULTS.append(("gpu_init_in_gui", repr(e)))
    try:
        setup_resources()
    except Exception as e:
        RESULTS.append(("setup_resources_FAIL", traceback.format_exc()))
    arm()
    bpy.app.timers.register(finish, first_interval=3.0)


main()
