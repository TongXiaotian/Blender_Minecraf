"""Blender 5.2.2 GPU/UI drawing reference — every snippet verified on
Blender 5.2.2 LTS (build d13f752e3b9c), Python 3.13.13, NumPy 2.3.4.

This file is also a valid addon: install it, then in the 3D Viewport
press F3 -> "Reference: Toggle Overlay".
"""
import numpy as np
import bpy
import blf
import gpu
from gpu.types import GPUBatch, GPUVertBuf, GPUVertFormat, GPUIndexBuf
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

bl_info = {
    "name": "5.2 GPU Draw API Reference",
    "blender": (5, 2, 0),
    "category": "Development",
}

# ---------------------------------------------------------------- 7) atlas image
def make_atlas_image(name="Atlas", size=256):
    """In-memory image that never touches disk."""
    img = bpy.data.images.new(name, width=size, height=size,
                              alpha=True, float_buffer=False)
    img.source = 'GENERATED'          # not a file on disk
    img.filepath = ""                 # no path
    img.use_fake_user = True          # survive .blend save/reload
    img.colorspace_settings.name = 'sRGB'
    a = np.zeros((size, size, 4), dtype=np.float32)   # (H, W, RGBA), bottom-up
    a[..., 3] = 1.0
    a[0, 0] = (1.0, 0.0, 0.0, 1.0)
    img.pixels.foreach_set(a.ravel())  # np.ndarray, must be contiguous+right size
    img.update()
    return img


# ------------------------------------------------------- 4) batch builders (2D)
def flat_quad_batch(shader):
    """2D positions. ``pos`` is declared VEC3 by the shader but 2D data is
    fine (missing components default to 0/1) — this is what Blender's own
    gpu_extras.presets / _bpy_types do."""
    fmt = GPUVertFormat()
    pos = fmt.attr_add(id="pos", comp_type='F32', len=2, fetch_mode='FLOAT')
    vbo = GPUVertBuf(len=4, format=fmt)
    vbo.attr_fill(id=pos, data=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    ibo = GPUIndexBuf(type='TRIS', seq=[(0, 1, 2), (2, 3, 0)])
    return GPUBatch(type='TRIS', buf=vbo, elem=ibo)


def textured_quad_batch(shader, u0=0.0, v0=0.0, u1=1.0, v1=1.0):
    """2D positions + UVs, built by the helper."""
    pos = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    return batch_for_shader(shader, 'TRIS',
                            {"pos": pos, "texCoord": uv},
                            indices=[(0, 1, 2), (2, 3, 0)])


def ortho_pixel_matrix(width, height, near=-1.0, far=1.0):
    """Replacement for the non-existent gpu.matrix.load_orthographic()."""
    return Matrix((
        (2.0 / width, 0.0, 0.0, -1.0),
        (0.0, 2.0 / height, 0.0, -1.0),
        (0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near)),
        (0.0, 0.0, 0.0, 1.0),
    ))


# --------------------------------------------------------------- 6) draw handler
class Overlay:
    _handle = None
    _draw = False

    def __init__(self):
        self.tex = None
        self.img = None
        self.shader_flat = None
        self.shader_img = None
        self.batch_flat = None
        self.batch_tex = None

    def setup(self):
        import os
        self.img = make_atlas_image("RefAtlas", 64)
        self.tex = gpu.texture.from_image(self.img)
        self.shader_flat = gpu.shader.from_builtin('UNIFORM_COLOR')   # 2D flat colour
        self.shader_img = gpu.shader.from_builtin('IMAGE')            # 2D textured
        self.batch_flat = flat_quad_batch(self.shader_flat)
        self.batch_tex = textured_quad_batch(self.shader_img)

    def draw(self):
        # In a WINDOW/POST_PIXEL handler the projection is ALREADY
        # window-pixel ortho with origin at bottom-left, modelview identity.
        # Nothing has to be set for plain pixel-space drawing.
        region = bpy.context.region          # valid inside the callback
        space = bpy.context.space_data       # valid inside the callback
        if region is None or space is None or space.type != 'VIEW_3D':
            return
        w, h = region.width, region.height

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)
        gpu.state.face_culling_set('NONE')
        gpu.state.line_width_set(1.0)

        # --- flat colour quad at pixel (60, 60), 240x160 ---
        with gpu.matrix.push_pop():
            gpu.matrix.translate((60.0, 60.0))
            gpu.matrix.scale((240.0, 160.0))
            self.shader_flat.uniform_float("color", (1.0, 0.45, 0.1, 0.85))
            self.batch_flat.draw(self.shader_flat)

        # --- textured quad at pixel (340, 60), 160x160 ---
        with gpu.matrix.push_pop():
            gpu.matrix.translate((340.0, 60.0))
            gpu.matrix.scale((160.0, 160.0))
            self.shader_img.uniform_sampler("image", self.tex)
            self.batch_tex.draw(self.shader_img)

        # --- blf text ---
        blf.size(0, 20)                                  # NO dpi argument in 5.2
        blf.color(0, 1.0, 1.0, 1.0, 1.0)                 # r, g, b, a
        blf.position(0, 60.0, 40.0, 0.0)                 # x, y, z REQUIRED
        blf.draw(0, "flat  |  textured  |  blf")

        # --- optional explicit ortho override ---
        gpu.matrix.push_projection()
        gpu.matrix.load_projection_matrix(ortho_pixel_matrix(w, h))
        gpu.matrix.pop_projection()

    def enable(self):
        if self._handle is None:
            self._handle = bpy.types.SpaceView3D.draw_handler_add(
                Overlay._draw_cb, (self,), 'WINDOW', 'POST_PIXEL')
        self._draw = True

    def disable(self):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        self._draw = False

    @staticmethod
    def _draw_cb(op, _context=None):
        op.draw()


_overlay = None


class REF_OT_toggle(bpy.types.Operator):
    bl_idname = "ref.toggle_overlay"
    bl_label = "Reference: Toggle Overlay"

    def execute(self, context):
        global _overlay
        if _overlay._handle is None:
            _overlay.setup()
            _overlay.enable()
        else:
            _overlay.disable()
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def register():
    global _overlay
    _overlay = Overlay()
    bpy.utils.register_class(REF_OT_toggle)


def unregister():
    global _overlay
    if _overlay is not None:
        _overlay.disable()
    bpy.utils.unregister_class(REF_OT_toggle)


# --------------------- 8) shading / preview state, 7) image node interpolation
def set_material_preview(context):
    sh = context.space_data.shading
    sh.type = 'MATERIAL'            # 'WIREFRAME' | 'SOLID' | 'MATERIAL' | 'RENDERED'
    sh.color_type = 'TEXTURE'       # 'MATERIAL'|'OBJECT'|'RANDOM'|'VERTEX'|'TEXTURE'|'SINGLE'
    sh.light = 'STUDIO'             # 'STUDIO' | 'MATCAP' | 'FLAT'
    sh.background_type = 'VIEWPORT'  # 'THEME' | 'WORLD' | 'VIEWPORT'
    sh.background_color = (0.05, 0.05, 0.05)
    sh.studiolight_background_alpha = 0.0
    sh.use_scene_lights = False


def make_image_texture_node(mat, image):
    mat.use_nodes = True            # DEPRECATED in 5.2 (removal in 6.0)
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.interpolation = 'Closest'  # still valid: Linear/Closest/Cubic/Smart
    node.extension = 'CLIP'         # REPEAT/EXTEND/CLIP/MIRROR
    return node
