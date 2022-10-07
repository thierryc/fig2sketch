from . import  artboard, instance
from .context import context
import utils

def convert(figma_symbol):
    # A symbol is an artboard with a symbolID
    master = artboard.convert(figma_symbol)
    master['_class'] = 'symbolMaster'

    # Keep the base ID as the symbol reference, create a new one for the container
    master['symbolID'] = utils.gen_object_id(figma_symbol.id)
    master['do_objectID'] = utils.gen_object_id(figma_symbol.id, b'symbol_master')

    return master


def move_to_symbols_page(figma_symbol, sketch_symbol):
    # After the entire symbol is converted, move it to the Symbols page
    context.add_symbol(sketch_symbol)

    # Since we put the Symbol in a different page in Sketch, leave an instance where the Figma master used to be
    return instance.master_instance(figma_symbol)