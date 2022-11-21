from converter import utils
from . import base, positioning, rectangle
from sketchformat.layer_group import Group
from sketchformat.style import *
import copy


def convert(fig_group):
    return Group(
        **base.base_styled(fig_group),
    )


def post_process_frame(fig_group, sketch_group):
    convert_frame_style(fig_group, sketch_group)

    # Do nothing for fig groups, they translate directly to Sketch
    if not fig_group["resizeToFit"]:
        convert_frame_to_group(fig_group, sketch_group)

    return sketch_group


def convert_frame_to_group(fig_group, sketch_group):
    needs_clip_mask = not fig_group.get("frameMaskDisabled", False)
    if needs_clip_mask:
        # Add a clipping rectangle matching the frame size. No need to recalculate bounds
        # since the clipmask defines Sketch bounds (which match visible children)
        sketch_group.layers.insert(
            0, rectangle.make_clipping_rect(fig_group, sketch_group.frame)
        )
    else:
        # When converting from a frame to a group, the bounding box should be adjusted
        # The frame box in a fig doc can be smalled than the children bounds, but not so in Sketch
        # To do so, we resize the frame to match the children bbox and also move the children
        # so that the top-left corner sits at 0,0
        children_bbox = positioning.group_bbox(sketch_group.layers)
        vector = [children_bbox[0], children_bbox[2]]

        for child in sketch_group.layers:
            child.frame.x -= vector[0]
            child.frame.y -= vector[1]

        sketch_group.frame.x += vector[0]
        sketch_group.frame.y += vector[1]
        sketch_group.frame.width = children_bbox[1] - children_bbox[0]
        sketch_group.frame.height = children_bbox[3] - children_bbox[2]


def convert_frame_style(fig_group, sketch_group):
    # Convert frame styles
    # - Fill/stroke/bgblur -> Rectangle on bottom with that style
    # - Layer blur -> Rectangle with bgblur on top
    # - Shadows -> Keep in the group
    # TODO: This is one case where we could have both background blur and layer blur
    style = sketch_group.style

    # Fill and borders go on a rectangle on the bottom
    has_fills = any([f.isEnabled for f in style.fills])
    has_borders = any([b.isEnabled for b in style.borders])
    has_inner_shadows = any([b.isEnabled for b in style.innerShadows])
    has_bgblur = style.blur.isEnabled and style.blur.type == BlurType.BACKGROUND
    has_blur = style.blur.isEnabled and style.blur.type == BlurType.GAUSSIAN

    if has_fills or has_borders or has_bgblur:
        bgrect = rectangle.make_background_rect(
            fig_group, sketch_group.frame, "Frame Background"
        )
        bgrect.style.fills = style.fills
        bgrect.style.borders = style.borders
        bgrect.style.blur = Blur(type=BlurType.BACKGROUND, radius=style.blur.radius)
        bgrect.style.innerShadows = style.innerShadows

        sketch_group.layers.insert(0, bgrect)

        style.fills = []
        style.borders = []
        style.blur.isEnabled = False
        style.innerShadows = []

    # Blur goes in a rectangle with bgblur at the top
    if has_blur:
        blur = rectangle.make_background_rect(
            fig_group, sketch_group.frame, f"{sketch_group.name} blur"
        )
        blur.style.blur = Blur(type=BlurType.BACKGROUND, radius=style.blur.radius)

        # Foreground blur, add as a layer at the top of the group
        sketch_group.layers.append(blur)
        style.blur.isEnabled = False

    # Inner shadows apply to each child (if they were not put in the background rect earlier)
    # Normal shadows are untouched
    for shadow in style.innerShadows:
        utils.log_conversion_warning("GRP001", fig_group)
        apply_inner_shadow(sketch_group, shadow)

    style.innerShadows = []

    return sketch_group


def apply_inner_shadow(layer, shadow):
    if isinstance(layer, Group):
        for child in layer.layers:
            apply_inner_shadow(child, shadow)
    else:
        layer.style.innerShadows.append(shadow)
