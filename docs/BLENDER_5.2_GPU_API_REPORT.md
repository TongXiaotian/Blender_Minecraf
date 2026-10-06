# Blender 5.2.2 GPU / UI Drawing API — Verified Report

**Target:** Blender **5.2.2 LTS**, build `d13f752e3b9c`, build date 2026-09-15, branch `blender-v5.2-release`
**Install:** `E:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
**Bundled Python:** **3.13.13** (MSC v.1944, 64-bit) — `E:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe`
**Bundled NumPy:** **2.3.4** — `...\5.2\python\Lib\site-packages\numpy\__init__.py`
**GPU backend measured here:** OPENGL, `Intel(R) Iris(R) Xe Graphics`, GL 4.6.0

### How each claim was verified

* **Local grep** of `...\5.2\scripts\modules\**` and `...\5.2\scripts\addons_core\**`.
* **Live introspection**: `blender.exe --background --python` probes calling the real API and reading `__doc__` / RNA enums.
* **Live GUI end-to-end**: a real `SpaceView3D` `'WINDOW','POST_PIXEL'` draw handler was registered on a running GUI Blender; inside it the *actual* projection matrix, context, shaders, batches, textured quad, `IMAGE_COLOR` tint and `blf.draw` were exercised. All returned OK.
* `docs.blender.org/api/current/gpu.html` returned **HTTP 403** (Cloudflare), so **no online corroboration** was possible. Everything below is verified against the local installation. Items I could not verify are flagged **unverified**.

---

## 1. `gpu.shader.from_builtin(...)` — exact valid names in 5.2

Signature (verified from `__doc__`): `gpu.shader.from_builtin(shader_name, *, config='DEFAULT')`
`config` accepts exactly `'DEFAULT'` or `'CLIPPED'` (error enumerates these; `'BATCHED'`/`'INSTANCED'`/`'NONE'` are invalid).

Calling it with a bogus name raises `ValueError` whose message **enumerates the complete valid set**. Copy-pasted verbatim from 5.2.2:

```
expected a string in ('FLAT_COLOR', 'IMAGE', 'IMAGE_SCENE_LINEAR_TO_REC709_SRGB', 'IMAGE_COLOR',
'IMAGE_COLOR_SCENE_LINEAR_TO_REC709_SRGB', 'SMOOTH_COLOR', 'UNIFORM_COLOR',
'POLYLINE_FLAT_COLOR', 'POLYLINE_SMOOTH_COLOR', 'POLYLINE_UNIFORM_COLOR',
'POINT_FLAT_COLOR', 'POINT_UNIFORM_COLOR')
```

That is the **complete** list — 12 names. Answering your specific questions:

| Need | 5.2 name | Notes |
|---|---|---|
| 2D flat colour | `'UNIFORM_COLOR'` | `pos` is declared `VEC3`; 2D tuples work (see §3) |
| 2D textured / image | `'IMAGE'` | or `'IMAGE_SCENE_LINEAR_TO_REC709_SRGB'` (colour-space variant) |
| 2D textured + tint | `'IMAGE_COLOR'` | adds a `color` uniform |
| 3D flat colour | `'UNIFORM_COLOR'` | **same shader** — there is no `'3D_FLAT_COLOR'` |
| per-vertex colour | `'FLAT_COLOR'` | colour comes from a vertex attribute, not a uniform |

**Deprecations / removals (all confirmed invalid in 5.2.2):**
`'2D_IMAGE'`, `'2D_IMAGE_COLOR'`, `'2D_UNIFORM_COLOR'`, `'2D_FLAT_COLOR'`, `'2D_SMOOTH_COLOR'`, `'2D_IMAGE_TILING'`, `'2D_IMAGE_RECT'`, `'2D_IMAGE_DEPTH'`, `'2D_POINT_UNIFORM_SIZE_UNIFORM_COLOR_AA'`, `'3D_UNIFORM_COLOR'`, `'3D_FLAT_COLOR'`, `'3D_SMOOTH_COLOR'`, `'3D_IMAGE'`, `'LINE_UNIFORM_COLOR'`, `'LINE_SMOOTH_COLOR'`, `'POINT_SMOOTH_COLOR'`, `'IMAGE_TILING'`, `'MASK'`, `'DEPTH_32F'`, `'DEPTH_24'`.

> **So: `'2D_IMAGE'` is gone. Use `'IMAGE'`. `'2D_IMAGE_COLOR'` is gone. Use `'IMAGE_COLOR'`.**
> The `2D_`/`3D_` prefix scheme was dropped in the 4.0 rename and has not returned in 5.2.

Attributes per shader (`shader.attrs_info_get()`, verified live):

| Shader | `attrs_info_get()` | internal name |
|---|---|---|
| `UNIFORM_COLOR` | `(('pos','VEC3'),)` | `gpu_shader_3D_uniform_color` |
| `FLAT_COLOR` | `(('pos','VEC3'),('color','VEC4'))` | `gpu_shader_3D_flat_color` |
| `SMOOTH_COLOR` | `(('pos','VEC3'),('color','VEC4'))` | `gpu_shader_3D_smooth_color` |
| `IMAGE` | `(('pos','VEC3'),('texCoord','VEC2'))` | `gpu_shader_3D_image` |
| `IMAGE_COLOR` | `(('pos','VEC3'),('texCoord','VEC2'))` | `gpu_shader_3D_image_color` |
| `IMAGE_SCENE_LINEAR_TO_REC709_SRGB` | `(('pos','VEC3'),('texCoord','VEC2'))` | `gpu_shader_3D_image_scene_linear` |
| `IMAGE_COLOR_SCENE_LINEAR_TO_REC709_SRGB` | `(('pos','VEC3'),('texCoord','VEC2'))` | `gpu_shader_3D_image_color_scene_linear` |
| `POLYLINE_UNIFORM_COLOR` | `(('pos','VEC3'),)` | `gpu_shader_3D_polyline_uniform_color` |
| `POLYLINE_FLAT_COLOR` | `(('pos','VEC3'),('color','VEC4'))` | `gpu_shader_3D_polyline_flat_color` |
| `POLYLINE_SMOOTH_COLOR` | `(('pos','VEC3'),('color','VEC4'))` | `gpu_shader_3D_polyline_smooth_color` |
| `POINT_UNIFORM_COLOR` | `(('pos','VEC3'),)` | `gpu_shader_3D_point_uniform_color` |
| `POINT_FLAT_COLOR` | `(('pos','VEC3'),('color','VEC4'))` | `gpu_shader_3D_point_flat_color` |

In-tree confirmation that these are the names to use:
`...\5.2\scripts\modules\gpu_extras\presets.py:54,88` (`POLYLINE_UNIFORM_COLOR`, `IMAGE`/`IMAGE_SCENE_LINEAR_TO_REC709_SRGB`),
`...\scripts\modules\_bpy_types.py:1083` (`UNIFORM_COLOR`),
`...\scripts\addons_core\io_mesh_uv_layout\export_uv_png.py:75,97` (`FLAT_COLOR`, `POLYLINE_UNIFORM_COLOR`),
`...\scripts\addons_core\node_wrangler\utils\draw.py:14,36,64` (`POLYLINE_SMOOTH_COLOR`, `UNIFORM_COLOR`),
`...\scripts\templates_py\Operator\modal_draw.py:19`.

---

## 2. Uniform names + exact setter calls

`GPUShader` methods (verified `dir()`): `uniform_float`, `uniform_int`, `uniform_bool`, `uniform_vector_float`, `uniform_vector_int`, `uniform_sampler`, `uniform_block`, `uniform_block_from_name`, `uniform_from_name`, `attr_from_name`, `attrs_info_get`, `bind`, `format_calc`, `image`, `name`, `program`.
There is **no uniform-enumeration API**; an unknown name raises `ValueError: GPUShader.uniform_float: uniform <name> not found`.

Uniform **names** below were probed live on 5.2.2. `ModelViewProjectionMatrix` is auto-set by `batch.draw(shader)` — **never set it yourself**.

| Shader | Uniforms you set |
|---|---|
| `UNIFORM_COLOR` | `color` |
| `FLAT_COLOR` | *(none — `color` is a vertex attribute)* |
| `SMOOTH_COLOR` | *(none — `color` is a vertex attribute)* |
| `IMAGE` | `image` |
| `IMAGE_COLOR` | `color`, `image` |
| `IMAGE_SCENE_LINEAR_TO_REC709_SRGB` | `image` |
| `IMAGE_COLOR_SCENE_LINEAR_TO_REC709_SRGB` | `color`, `image` |
| `POLYLINE_UNIFORM_COLOR` | `color`, `viewportSize`, `lineWidth` |
| `POLYLINE_FLAT_COLOR` | `viewportSize`, `lineWidth` |
| `POLYLINE_SMOOTH_COLOR` | `viewportSize`, `lineWidth` |
| `POINT_UNIFORM_COLOR` | `color`, `size` |
| `POINT_FLAT_COLOR` | `size` |

Exact calls:

```python
shader.uniform_float("color", (1.0, 0.45, 0.1, 0.85))            # vec4
shader.uniform_float("lineWidth", 1.0)                            # float
shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])  # 2 floats
shader.uniform_float("size", 6.0)                                 # float
shader.uniform_sampler("image", gputexture)                       # GPUTexture, NOT None
```

`uniform_sampler` rejects `None`: `TypeError: GPUShader.uniform_sampler() argument 2 must be GPUTexture, not None`.
`viewportSize` must be a 2-element sequence — `gpu.state.viewport_get()` returns a 4-tuple `(x, y, w, h)`, hence the `[2:]` slice (this is exactly what `gpu_extras\presets.py:55` and `export_uv_png.py:98` do).

---

## 3. Screen-space (pixel) quad in a `SpaceView3D` WINDOW handler

### The key finding: you need no matrix setup at all

`gpu.matrix.load_orthographic` **does not exist** in 5.2. Neither does `gpu.matrix.ortho`.
Complete `gpu.matrix` API (verified `dir()` in 5.2.2):

```
get_model_view_matrix, get_normal_matrix, get_projection_matrix, load_identity, load_matrix,
load_projection_matrix, multiply_matrix, pop, pop_projection, push,
push_pop, push_pop_projection, push_projection, reset, scale, scale_uniform, translate
```

`mathutils.Matrix.Ortho` **also does not exist** (`AttributeError: type object 'Matrix' has no attribute 'Ortho'`). The real helper is `Matrix.OrthoProjection` (different thing) — I did not test it.

I dumped the *actual* matrices inside a live `WINDOW`/`POST_PIXEL` handler on a 1574×869 viewport:

```python
proj = [[0.001270647975616157, 0.0, 0.0, -0.9999873042106628],
        [0.0, 0.002301495987921953, 0.0, -0.9999769330024719],
        [0.0, 0.0, -0.009999999776482582, -0.0],
        [0.0, 0.0, 0.0, 1.0]]
modelview = identity
viewport  = (0, 0, 1574, 869)
```

`0.0012706… == 2/1574` and `0.0023014… == 2/869`, with the translation terms at `-1`: this is a **pixel-space ortho projection with origin at the bottom-left**. The modelview matrix is **identity**.
**Therefore, in a `WINDOW`/`POST_PIXEL` handler you simply draw in window pixel coordinates.** That is why every in-tree addon (`gpu_extras\presets.py`, `node_wrangler\utils\draw.py`, `modal_draw.py`, `export_uv_png.py`) draws raw pixel coordinates without touching `gpu.matrix` at all.

Initial pipeline state measured at entry: `gpu.state.blend_get() == 'NONE'` and `gpu.state.depth_test_get() == 'NONE'`. So you **must** call `blend_set('ALPHA')` for transparency.

### Verified state enums (from the `ValueError` messages)

```python
gpu.state.blend_set(...)        # 'NONE','ALPHA','ALPHA_PREMULT','ADDITIVE','ADDITIVE_PREMULT','MULTIPLY','SUBTRACT','INVERT'
gpu.state.depth_test_set(...)   # 'NONE','ALWAYS','LESS','LESS_EQUAL','EQUAL','GREATER','GREATER_EQUAL'
gpu.state.face_culling_set(...) # 'NONE','FRONT','BACK'
gpu.state.depth_mask_set(bool)
gpu.state.line_width_set(float) ; gpu.state.point_size_set(float)
gpu.state.viewport_get() / viewport_set() / scissor_get() / scissor_set()
gpu.state.active_framebuffer_get()
```

### Copy-pasteable handler body (all of this ran successfully on 5.2.2)

```python
import bpy
import gpu
from mathutils import Matrix


def ortho_pixel_matrix(width, height, near=-1.0, far=1.0):
    """Manual replacement for the non-existent gpu.matrix.load_orthographic()."""
    return Matrix((
        (2.0 / width, 0.0, 0.0, -1.0),
        (0.0, 2.0 / height, 0.0, -1.0),
        (0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near)),
        (0.0, 0.0, 0.0, 1.0),
    ))


def draw_pixel_quad(batch, shader):
    """Screen-space quad. WINDOW/POST_PIXEL handlers already run in pixel space."""
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(False)
    gpu.state.face_culling_set('NONE')
    gpu.state.line_width_set(1.0)

    # translate+scale from a unit quad -> pixels; push_pop() keeps it balanced
    with gpu.matrix.push_pop():
        gpu.matrix.translate((100.0, 100.0))     # lower-left in window pixels
        gpu.matrix.scale((200.0, 150.0))         # size in pixels
        shader.uniform_float("color", (1.0, 0.4, 0.1, 0.8))
        batch.draw(shader)

    # Explicit projection override (only if you really want one):
    # gpu.matrix.push_projection()
    # gpu.matrix.load_projection_matrix(ortho_pixel_matrix(1920, 1080))
    # ... draw ...
    # gpu.matrix.pop_projection()
```

`gpu.matrix.push_pop()` is a **context manager** (verified) and is the safe idiom; `push()`/`pop()` also exist, as do `push_projection()`/`pop_projection()`/`push_pop_projection()`. `load_identity()` and `load_matrix(m)` work. `load_projection_matrix(matrix)` accepts a `mathutils.Matrix` and round-trips exactly.

---

## 4. Textured quad with an existing `bpy.types.Image` atlas

`gpu.texture.from_image` **is still valid** — and it is the *only* function in the `gpu.texture` module in 5.2 (`dir(gpu.texture) == ['from_image']`). Signature: `from_image(image)`. It worked on a generated image and produced `format='SRGB8_A8'` for an 8-bit sRGB image.

```python
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from gpu.types import GPUBatch, GPUVertBuf, GPUVertFormat, GPUIndexBuf

image = bpy.data.images["MyAtlas"]          # any bpy.types.Image with pixels
texture = gpu.texture.from_image(image)     # -> gpu.types.GPUTexture

# --- Variant A: helper (recommended) -------------------------------------
shader = gpu.shader.from_builtin('IMAGE')            # 2D textured
pos = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
uv  = [(0.00, 0.00), (0.50, 0.00), (0.50, 0.50), (0.00, 0.50)]  # atlas sub-rect
batch = batch_for_shader(
    shader, 'TRIS',
    {"pos": pos, "texCoord": uv},
    indices=[(0, 1, 2), (2, 3, 0)],
)

with gpu.matrix.push_pop():
    gpu.matrix.translate((340.0, 60.0))
    gpu.matrix.scale((160.0, 160.0))
    shader.uniform_sampler("image", texture)
    batch.draw(shader)

# --- Variant B: fully manual vertex format -------------------------------
fmt = GPUVertFormat()
pos_id = fmt.attr_add(id="pos",      comp_type='F32', len=2, fetch_mode='FLOAT')
uv_id  = fmt.attr_add(id="texCoord", comp_type='F32', len=2, fetch_mode='FLOAT')
vbo = GPUVertBuf(len=4, format=fmt)
vbo.attr_fill(id=pos_id, data=pos)
vbo.attr_fill(id=uv_id,  data=uv)
ibo = GPUIndexBuf(type='TRIS', seq=[(0, 1, 2), (2, 3, 0)])
batch_manual = GPUBatch(type='TRIS', buf=vbo, elem=ibo)
```

* Attribute names are exactly **`pos`** and **`texCoord`** (capital C) — verified via `attrs_info_get()`.
* Passing 2D tuples for `pos` while the shader declares `VEC3` is correct and idempotent; `batch_for_shader` sizes the buffer from your data. This is what `_bpy_types.py:1075-1083` and `gpu_extras\presets.py:85-94` do.
* **`TRI_FAN` is deprecated**: `DeprecationWarning: 'TRI_FAN' is deprecated. Please use 'TRI_STRIP' or 'TRIS' and try modifying your vertices or indices to match the topology.` Use `TRIS`/`TRI_STRIP`.
* **Colour space:** `gpu_extras\presets.py:74-89` documents that when drawing a `bpy.types.Image` inside a `'PRE_VIEW'`, `'POST_VIEW'` or `'POST_PIXEL'` handler, the framebuffer is Rec.709 sRGB, so if your texture is scene-linear you should use `'IMAGE_SCENE_LINEAR_TO_REC709_SRGB'` instead of `'IMAGE'`. If you need a tint, use `'IMAGE_COLOR'` (`shader.uniform_float("color", (r, g, b, a))` then `shader.uniform_sampler("image", texture)`) — verified drawing OK.

---

## 5. `blf` in 5.2 — exact signatures (from `__doc__`, then called live)

```
blf.size(fontid, size)                 # EXACTLY 2 args — dpi is GONE
blf.color(fontid, r, g, b, a)          # 4 floats
blf.position(fontid, x, y, z)          # EXACTLY 4 args — z is REQUIRED
blf.draw(fontid, text)
blf.dimensions(fontid, text) -> (w, h)
blf.shadow(fontid, level, r, g, b, a)  # level: 0 none, 3, 5, or 6 outline
blf.enable(fontid, option) / blf.disable(fontid, option)
blf.rotation(fontid, angle)
blf.aspect(fontid, aspect)
blf.shadow_offset(fontid, x, y)
blf.word_wrap(fontid, wrap_width)
blf.load(filepath) -> fontid ; blf.unload(filepath)
```

Answers to your two questions, both empirically proven:

* **`blf.size` does NOT take a dpi argument.** `blf.size(0, 20)` → OK. `blf.size(0, 20, 72)` → `TypeError: blf.size() takes exactly 2 arguments (3 given)`. `blf.size(0, 20, dpi=72)` → `TypeError: size() takes no keyword arguments`. The string `dpi` does not appear anywhere in the bundled blf docs.
* **`blf.color` takes `fontid` + 4 floats**: `blf.color(0, 1.0, 1.0, 1.0, 1.0)` → OK.
* **`blf.position` requires `z`**: `blf.position(0, 0.0, 0.0)` → `TypeError: blf.position() takes exactly 4 arguments (3 given)`; `blf.position(0, x, y, 0.0)` → OK. (In older versions `z` had a default — it does not in 5.2.)

Working snippet (ran in a real handler):

```python
import blf

blf.size(0, 20)                       # fontid 0 = default font
blf.color(0, 1.0, 1.0, 1.0, 1.0)
blf.position(0, 50.0, 50.0, 0.0)      # z is mandatory
blf.draw(0, "Blender 5.2 blf test")

w, h = blf.dimensions(0, "Blender 5.2 blf test")   # measured: (174.0, 15.0) at size 20
```

`blf` also gained `bind_imbuf`, `draw_buffer` and the constants `ROTATION, CLIPPING, SHADOW, MONOCHROME, WORD_WRAP, NO_FALLBACK`.

---

## 6. `SpaceView3D.draw_handler_add` and context inside the callback

Exact signature (from `__doc__`, verified present on `SpaceView3D`):

```python
bpy.types.SpaceView3D.draw_handler_add(callback, args, region_type, draw_type)  # classmethod
bpy.types.SpaceView3D.draw_handler_remove(handler, region_type)                 # classmethod
```

It returns an opaque capsule — verified: `<capsule object "RNA_HANDLE" at 0x…>`.
`draw_handler_add` is exposed by `Space, SpaceClipEditor, SpaceConsole, SpaceDopeSheetEditor, SpaceFileBrowser, SpaceGraphEditor, SpaceImageEditor, SpaceInfo, SpaceNLA, SpaceNodeEditor, SpaceOutliner, SpacePreferences, SpaceProperties, SpaceSequenceEditor, SpaceSpreadsheet, SpaceTextEditor, SpaceView3D` (verified list). It is a Python/C-level classmethod, *not* an RNA function (`'draw_handler_add' in SpaceView3D.bl_rna.functions` is `False`), so its `region_type`/`draw_type` enum strings are **not enumerable from Python — unverified**. `'WINDOW'` + `'POST_PIXEL'` is proven to work (see §3 and the in-tree usages below).

### `bpy.context.region` / `bpy.context.space_data` inside the callback — **YES, they work**

Measured live inside the handler:

```python
bpy.context.region     -> ('WINDOW', 1574, 869)   # type, width, height
bpy.context.space_data -> 'VIEW_3D'
bpy.context.area       -> 'VIEW_3D'
```

Corroborated in-tree: `...\scripts\addons_core\node_wrangler\utils\draw.py:68-157` calls `bpy.context.region.view2d.view_to_region(...)` from helper functions that are only reached through `draw_callback_nodeoutline(self, context, mode)` (line 171), which is registered at `...\node_wrangler\operators\lazy_mix.py:90-91` with `('WINDOW', 'POST_PIXEL')`.

**Recommendation:** capture nothing defensively, but *do* guard, because the handler is invoked once per region and per quad-view:

```python
def draw_callback_px(op, context=None):
    region = bpy.context.region
    space = bpy.context.space_data
    if region is None or space is None or space.type != 'VIEW_3D':
        return
    w, h = region.width, region.height
    ...

handle = bpy.types.SpaceView3D.draw_handler_add(
    draw_callback_px, (self,), 'WINDOW', 'POST_PIXEL')
# later, must match region_type:
bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
```

(The older idiom of passing `context` via `args` at add time — as in `templates_py\Operator\modal_draw.py:56` — still works; the `context` captured then is the one live at registration, which is why reading `bpy.context` at draw time is generally preferable.)

---

## 7. Images, pixels, and node interpolation

`bpy.data.images.new` exact 5.2 signature (from `__doc__`):

```python
bpy.data.images.new(name, width, height, alpha=False, float_buffer=False,
                    stereo3d=False, is_data=False, tiled=False)
```

Note `alpha` **defaults to False** — pass `alpha=True` explicitly.

**`foreach_set(numpy)` still works** — verified, and it is the fast path:

```python
import numpy as np
img = bpy.data.images.new("Atlas", 256, 256, alpha=True, float_buffer=False)
a = np.zeros((256, 256, 4), dtype=np.float32)   # (H, W, RGBA), row 0 = BOTTOM
a[..., 3] = 1.0
img.pixels.foreach_set(a.ravel())               # OK, marks img.is_dirty = True
```

* `image.pixels.foreach_get(buf)` requires a buffer of **exactly** `w*h*channels`; a wrong size raises `TypeError: expected sequence size 64, got 16`.
* `image.pixels[:] = [...]` (plain slice assignment) **also still works** — but `foreach_set` with a contiguous `np.ndarray` is the recommended fast path.
* **Breaking:** `bpy.types.ImagePixels` **no longer exists** in 5.2 (`bpy.types has ImagePixels: False`). `image.pixels` is now a plain `bpy_prop_array` (RNA `FloatProperty` with `is_array=True`). Don't reference `bpy.types.ImagePixels` in type hints or `isinstance` checks.

**Not saving to disk:**

```python
img.source = 'GENERATED'    # default for images.new; not backed by a file
img.filepath = ""           # no path
img.use_fake_user = True    # survive .blend save/reload
# never call img.save() / img.save_render() / img.save_render(filepath=...)
img.pack()                  # optional, but see caveat
```
Caveat, measured: `img.pack()` **flips `img.source` from `'GENERATED'` to `'FILE'`** and creates a `PackedFile`, while `filepath` stays `''`. It still never touches disk, but if you want to keep `source == 'GENERATED'` semantics, just don't call `pack()`.

**Interpolation:** the **`Image` datablock has no `interpolation` property any more** (`Image.interpolation prop: False`; it is absent from the full `Image` property list). Set it on the **texture node**, and `'Closest'` **is still valid**:

```python
mat = bpy.data.materials.new("m")
mat.use_nodes = True            # DEPRECATED in 5.2 — see §9
node = mat.node_tree.nodes.new("ShaderNodeTexImage")
node.image = img
node.interpolation = 'Closest'  # enum: 'Linear' (default), 'Closest', 'Cubic', 'Smart'
node.extension = 'CLIP'         # enum: 'REPEAT' (default), 'EXTEND', 'CLIP', 'MIRROR'
```
Both assignments verified live. `ShaderNodeTexImage.projection` is `'FLAT'|'BOX'|'SPHERE'|'TUBE'`.

---

## 8. `SpaceView3D.shading` — attributes valid in 5.2

`bpy.types.SpaceView3D.bl_rna.properties['shading']` → `View3DShading` (verified).
**Current valid `shading.type` values: `'WIREFRAME'`, `'SOLID'`, `'MATERIAL'`, `'RENDERED'`.**

> **`shading.type = 'TEXTURE'` is INVALID in 5.2.** The old `'TEXTURE'` viewport mode is gone. For a TEXTURE preview use `shading.type = 'SOLID'` (or `'MATERIAL'`) together with `shading.color_type = 'TEXTURE'`.

Complete verified enum/property table:

| Property | Type / valid values | Default |
|---|---|---|
| `type` | `'WIREFRAME'`, `'SOLID'`, `'MATERIAL'`, `'RENDERED'` | `SOLID` |
| `color_type` | `'MATERIAL'`, `'OBJECT'`, `'RANDOM'`, `'VERTEX'`, `'TEXTURE'`, `'SINGLE'` | `MATERIAL` |
| `light` | `'STUDIO'`, `'MATCAP'`, `'FLAT'` | `STUDIO` |
| `background_type` | `'THEME'`, `'WORLD'`, `'VIEWPORT'` | `THEME` |
| `wireframe_color_type` | `'THEME'`, `'OBJECT'`, `'RANDOM'` | — |
| `cavity_type` | `'WORLD'`, `'SCREEN'`, `'BOTH'` | — |
| `render_pass` | `'COMBINED'`, `'EMISSION'`, `'ENVIRONMENT'`, `'AO'`, `'SHADOW'`, `'TRANSPARENT'`, `'DIFFUSE_LIGHT'`, `'DIFFUSE_COLOR'`, `'SPECULAR_LIGHT'`, `'SPECULAR_COLOR'`, `'VOLUME_LIGHT'`, `'POSITION'`, `'NORMAL'`, `'MIST'`, `'CryptoObject'`, `'CryptoAsset'`, `'CryptoMaterial'`, `'AOV'` | — |
| `background_color` | `FLOAT[3]` | — |
| `single_color` | `FLOAT` | — |
| `studiolight_background_alpha` | `FLOAT` | `0.0` |
| `studiolight_background_blur` | `FLOAT` | — |
| `studiolight_intensity` | `FLOAT` | — |
| `studiolight_rotate_z` | `FLOAT` | — |
| `shadow_intensity`, `xray_alpha`, `xray_alpha_wireframe` | `FLOAT` | — |
| `cavity_ridge_factor`, `cavity_valley_factor`, `curvature_ridge_factor`, `curvature_valley_factor` | `FLOAT` | — |
| `use_scene_lights`, `use_scene_world`, `use_scene_lights_render`, `use_scene_world_render`, `use_world_space_lighting`, `use_dof`, `use_compositor`, `use_studiolight_view_rotation` | `BOOL` | `use_scene_lights=False` |
| `show_shadows`, `show_cavity`, `show_object_outline`, `show_specular_highlight`, `show_xray`, `show_xray_wireframe`, `show_backface_culling` | `BOOL` | — |
| `studio_light`, `selected_studio_light`, `aov_name`, `object_outline_color`, `cycles` | misc | — |

Full verified property list (41 entries):
`aov_name, background_color, background_type, cavity_ridge_factor, cavity_type, cavity_valley_factor, color_type, curvature_ridge_factor, curvature_valley_factor, cycles, light, object_outline_color, render_pass, selected_studio_light, shadow_intensity, show_backface_culling, show_cavity, show_object_outline, show_shadows, show_specular_highlight, show_xray, show_xray_wireframe, single_color, studio_light, studiolight_background_alpha, studiolight_background_blur, studiolight_intensity, studiolight_rotate_z, type, use_compositor, use_dof, use_scene_lights, use_scene_lights_render, use_scene_world, use_scene_world_render, use_studiolight_view_rotation, use_world_space_lighting, wireframe_color_type, xray_alpha, xray_alpha_wireframe`

**`show_gizmo` is NOT on `View3DShading`** — it lives on `SpaceView3D` (`space_view3d.py:6114` does `pie.prop(context.space_data, "show_gizmo", ...)`).

Working snippet (ran live; readback gave `shading.type == 'SOLID'`):

```python
sh = context.space_data.shading
sh.type = 'SOLID'                       # or 'MATERIAL'
sh.color_type = 'TEXTURE'               # texture preview
sh.light = 'STUDIO'
sh.background_type = 'VIEWPORT'
sh.background_color = (0.05, 0.05, 0.05)
sh.studiolight_background_alpha = 0.0
sh.use_scene_lights = False
```

---

## 9. 5.x breaking changes vs 4.x that affect this addon

| Change | Status in 5.2.2 | Evidence |
|---|---|---|
| **`bgl` removed entirely** | `import bgl` → `ModuleNotFoundError: No module named 'bgl'` | live probe |
| **`2D_*` / `3D_*` builtin shader names removed** | only the 12 names in §1 are valid; error message enumerates them | live probe |
| **`gpu.init()` is new and required in `--background`** | without it every GPU call raises `SystemError: GPU functions for drawing requires the gpu module to be initialized. See gpu.init.` `gpu.init()` exists, returns `None`, and is harmless/idempotent in the GUI | `dir(gpu)` now includes `init`; `__doc__` = `init()` |
| **`gpu.matrix.load_orthographic` / `gpu.matrix.ortho`** | never present in 5.2 (`hasattr` → `False`); use a manual `mathutils.Matrix` + `load_projection_matrix`, or rely on the built-in pixel ortho | live probe |
| **`TRI_FAN` deprecated** | `DeprecationWarning`; use `TRI_STRIP`/`TRIS` | live probe |
| **`Material.use_nodes` deprecated** | `DeprecationWarning: 'Material.use_nodes' is expected to be removed in Blender 6.0` — start using `mat.node_tree` access patterns that don't toggle `use_nodes`, and be ready for 6.0 | live probe |
| **`Mesh.calc_normals_split` removed** | `AttributeError: 'Mesh' object has no attribute 'calc_normals_split'`; use `mesh.corner_normals` / `mesh.vertex_normals` (both present) | live probe |
| **`bpy.types.ImagePixels` removed** | `image.pixels` is a `bpy_prop_array`; `foreach_get`/`foreach_set` remain | live probe |
| **`blf.size` lost its `dpi` argument** | exactly 2 args, no keywords | live probe |
| **`blf.position` requires `z`** | exactly 4 args | live probe |
| **`Image.interpolation` removed** | set `ShaderNodeTexImage.interpolation` instead | live probe |
| **`shading.type = 'TEXTURE'` removed** | use `type='SOLID'` + `color_type='TEXTURE'` | RNA enum |
| `gpu.shader.from_builtin` gained `config=` | `'DEFAULT'` \| `'CLIPPED'` | `__doc__` + error enum |
| **`bpy.ops.wm.*`** | **no removals found** — `save_as_mainfile, save_mainfile, open_mainfile, quit_blender, save_homefile, read_factory_settings, read_homefile, save_userpref, link, append, batch_rename_files` all present | live probe |
| **`window.cursor_warp`** | still exists, RNA function, params `(x, y)` | `Window.bl_rna.functions` |
| **`event_timer_add`** | still exists: `WindowManager.event_timer_add(time_step, window)`, plus `event_timer_remove(timer)` | `WindowManager.bl_rna.functions` |
| **`bpy.app.timers`** | still there: `register(function, *, first_interval=0, persistent=False)`, `unregister`, `is_registered` | `__doc__` |
| **`mesh.color_attributes.new`** | works: collection RNA identifier is `AttributeGroupMesh` (same as `mesh.attributes`), signature `new(name, type, domain, attribute)`; `type` enum `('FLOAT','INT','BOOLEAN','FLOAT_VECTOR','FLOAT_COLOR','QUATERNION','FLOAT4X4','STRING','INT8','INT16_2D','INT32_2D','FLOAT2','FLOAT4','BYTE_COLOR')`, `domain` enum `('POINT','EDGE','FACE','CORNER','CURVE','INSTANCE','LAYER')`. `mesh.color_attributes.new(name="C", type='FLOAT_COLOR', domain='CORNER')` verified. Collection also exposes `remove(attribute)` and `domain_size(domain, size)` and the metadata props `active_color_index`, `active_color_name`, `render_color_index`, `default_color_name`. **No `MeshColorAttribute`/`MeshColorAttributes` types any more.** | live probe |
| **`mesh.from_pydata`** | **still fine** — built 4 verts / 1 poly / 4 loops successfully | live probe |
| `mesh.shade_flat()` / `mesh.shade_smooth()` | still present as instance methods | live probe |

Extra `--background`-only gotcha worth knowing: in background mode the GPU is **not** initialised, so any addon that lazily touches `gpu.*` at import time will raise the `SystemError` above. Guard with a try/except `gpu.init()` or defer GPU work to draw handlers/operators.

---

## 10. NumPy and the bundled Python

* **Bundled Python: 3.13.13** — `3.13.13 (main, May 8 2026, 12:37:03) [MSC v.1944 64 bit (AMD64)]`, `sys.executable = E:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe`.
* **`import numpy` is guaranteed**: NumPy **2.3.4** ships inside the installation at `E:\Program Files\Blender Foundation\Blender 5.2\5.2\python\Lib\site-packages\numpy\__init__.py`. `import numpy as np` succeeded in every probe, in both `--background` and GUI sessions.

---

## Explicitly UNVERIFIED

1. **Exact `region_type` / `draw_type` enum strings for `draw_handler_add`.** They are validated in C, are not an RNA enum, and the `__doc__` does not list them, so I could not enumerate them. `'WINDOW'` + `'POST_PIXEL'` is **verified working**; the other commonly-cited values (`'HEADER'`, `'POST_VIEW'`, `'PRE_VIEW'`, `'BACKDROP'`, `'PAINT'`, `'CHANNEL'`, `'TEMPORARY'`) are **not verified here**.
2. **No online corroboration.** `https://docs.blender.org/api/current/gpu.html` returned **HTTP 403** (Cloudflare interstitial), so every statement above rests on the local 5.2.2 installation only — which is the same binary you are targeting, so this is stronger than docs anyway.
3. **Vulkan backend.** All measurements were taken on the OpenGL backend (`gpu.platform.backend_type_get() == 'OPENGL'`, Intel Iris Xe, GL 4.6.0). Behaviour on `--gpu-backend vulkan` was not tested.
4. **`mathutils.Matrix.OrthoProjection`** exists but I did not test its semantics; my verified ortho helper is the hand-built `Matrix(...)` above.

## Files produced

* `bl52_draw_reference.py` — tested, registering reference addon containing every snippet (validated: module import, `register()`, `unregister()`, texture creation, both batch builders, ortho matrix, texture-node setup all OK on 5.2.2).
* `gui_draw_result.json` — raw output of the live GUI `WINDOW`/`POST_PIXEL` draw-handler run.
* `bl52_probe.py`, `probe4.txt`–`probe9.txt` — raw probe scripts and outputs.
