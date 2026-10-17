"""Step 4 - layer property changes (autocad_set_layer_properties) in a scratch drawing, every result
checked against an independent direct-COM read of the layer, plus the refusal cases.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import Ctx, acase, case, must, short, tool  # noqa: E402

LAYER = "MCP_LIVE_A"


def same(a, b):
    return {k: (str(v).lower() if isinstance(v, str) else v) for k, v in a.items()} == {k: (str(v).lower() if isinstance(v, str) else v) for k, v in b.items()}


async def run(ctx: Ctx, base):
    d = ctx.data
    out = await tool(ctx, "autocad_create_new_drawing", {"pin": True}, label="setup")
    must(not out["is_error"], short(out["payload"]))
    d["name"] = out["payload"]["drawing_name"]
    doc = cp.active_doc()

    # which linetype will have to be loaded from the library?
    loaded = {n.lower() for n in cp.linetype_names(doc)}
    d["lt"] = next((n for n in ("DASHED", "HIDDEN", "CENTER", "PHANTOM", "DOT") if n.lower() not in loaded), "DASHED")
    d["lt_was_loaded"] = d["lt"].lower() in loaded
    print("linetypes already in the scratch drawing:", sorted(loaded), "-> will use", d["lt"], "(was loaded:", d["lt_was_loaded"], ")")

    expected = {}

    def chk_create(p):
        must(p["created"] is True and p["verified"] is True and p["color_index"] == 3, short(p))
        props = cp.layer_props(cp.active_doc(), LAYER)
        must(props is not None and props["color"] == 3, f"direct COM {props}")
        expected.update(props)
        d["initial"] = dict(props)
    await case(ctx, "LAY01", "D", "autocad_create_layer", {"name": LAYER, "color_index": 3}, "create the test layer (colour 3); direct COM shows it with default flags", check=chk_create, method="real-MCP-stdio+direct-COM")

    async def step(cid, title, args, change, *, before_keys=None):
        def chk(p):
            must(p["verified"] is True and p["mismatched"] == {}, short(p))
            expected.update(change)
            props = cp.layer_props(cp.active_doc(), LAYER)
            must(same(props, expected), f"direct COM layer {props} != expected {expected}")
            return None
        return await case(ctx, cid, "D", "autocad_set_layer_properties", {"name": LAYER, **args}, title, check=chk, method="real-MCP-stdio+direct-COM")

    await step("LAY02", "switch the layer off (on=false): only that flag changes, direct COM agrees", {"on": False}, {"on": False})
    await step("LAY03", "freeze it (frozen=true): only that flag changes", {"frozen": True}, {"frozen": True})
    await step("LAY04", "lock it (locked=true): only that flag changes", {"locked": True}, {"locked": True})
    await step("LAY05", "colour 5: only the colour changes", {"color_index": 5}, {"color": 5})

    lt = d["lt"]
    lt_before = cp.linetype_names(cp.active_doc())

    async def lt_step():
        def chk(p):
            must(p["verified"] is True, short(p))
            expected.update({"linetype": lt})
            props = cp.layer_props(cp.active_doc(), LAYER)
            must(same(props, expected), f"direct COM layer {props} != expected {expected}")
            after = [n.lower() for n in cp.linetype_names(cp.active_doc())]
            must(lt.lower() in after, f"{lt} should now be loaded in the drawing: {after}")
            return None
        return await case(ctx, "LAY06", "D", "autocad_set_layer_properties", {"name": LAYER, "linetype": lt},
                          f"linetype {lt}: loaded from the AutoCAD library when missing ({'already loaded' if d['lt_was_loaded'] else 'was NOT loaded before'}) and assigned",
                          check=chk, method="real-MCP-stdio+direct-COM")
    await lt_step()
    await step("LAY07", "lineweight 35 (0.35 mm): only the lineweight changes", {"lineweight": 35}, {"lineweight": 35})
    await step("LAY08", "plottable=false: only that flag changes", {"plottable": False}, {"plottable": False})
    await step("LAY09", "all seven properties in one call restore the defaults (on, thawed, unlocked, colour 1, Continuous, default weight, plottable)",
               {"on": True, "frozen": False, "locked": False, "color_index": 1, "linetype": "Continuous", "lineweight": -3, "plottable": True},
               {"on": True, "frozen": False, "locked": False, "color": 1, "linetype": "Continuous", "lineweight": -3, "plottable": True})

    def chk_lower(p):
        must(p["verified"] is True and p["layer_name"] == "mcp_live_a", short(p))
        props = cp.layer_props(cp.active_doc(), LAYER)
        must(props["on"] is False, f"direct COM {props}")
        expected["on"] = False
    await case(ctx, "LAY10", "D", "autocad_set_layer_properties", {"name": "mcp_live_a", "on": False}, "layer names are case-insensitive (lower-case spelling works)", check=chk_lower, method="real-MCP-stdio+direct-COM")
    await step("LAY11", "switch it back on", {"on": True}, {"on": True})

    # ---------------------------------------------------------------- refusals leave the layer exactly as it was
    def untouched(p):
        props = cp.layer_props(cp.active_doc(), LAYER)
        must(same(props, expected), f"layer changed by a refused call: {props} != {expected}")
    cur = cp.retry(lambda: cp.active_doc().ActiveLayer.Name)

    def chk_current(p):
        props = cp.layer_props(cp.active_doc(), cur)
        must(props["frozen"] is False, f"current layer {cur} must stay thawed: {props}")
    await case(ctx, "LAY12", "D", "autocad_set_layer_properties", {"name": cur, "frozen": True}, f"freezing the current layer ({cur}) is refused up front (E_INVALID_INPUT), layer stays thawed",
               expect_error="E_INVALID_INPUT", check=chk_current, method="real-MCP-stdio+direct-COM")

    def chk_missing(p):
        must(cp.layer_props(cp.active_doc(), "MCP_NO_SUCH_LAYER") is None, "a missing layer must not be created")
    await case(ctx, "LAY13", "D", "autocad_set_layer_properties", {"name": "MCP_NO_SUCH_LAYER", "on": False}, "unknown layer -> E_LAYER_NOT_FOUND and nothing is created", expect_error="E_LAYER_NOT_FOUND", check=chk_missing, method="real-MCP-stdio+direct-COM")
    await case(ctx, "LAY14", "D", "autocad_set_layer_properties", {"name": LAYER}, "no property given -> E_INVALID_INPUT", expect_error="E_INVALID_INPUT", check=untouched, method="real-MCP-stdio+direct-COM")
    await case(ctx, "LAY15", "D", "autocad_set_layer_properties", {"name": LAYER, "lineweight": 37}, "lineweight 37 is not an AutoCAD lineweight -> E_INVALID_INPUT, layer untouched", expect_error="E_INVALID_INPUT", check=untouched, method="real-MCP-stdio+direct-COM")
    await case(ctx, "LAY16", "D", "autocad_set_layer_properties", {"name": LAYER, "color_index": 300}, "colour 300 -> E_INVALID_INPUT, layer untouched", expect_error="E_INVALID_INPUT", check=untouched, method="real-MCP-stdio+direct-COM")
    await case(ctx, "LAY17", "D", "autocad_set_layer_properties", {"name": LAYER, "linetype": "NO_SUCH_LINETYPE"}, "a linetype that is in no library -> E_INVALID_INPUT, layer untouched", expect_error="E_INVALID_INPUT", check=untouched, method="real-MCP-stdio+direct-COM")
    await case(ctx, "LAY18", "D", "autocad_set_layer_properties", {"name": LAYER, "linetype": 'BAD"NAME'}, "a linetype name with illegal characters is rejected before any COM call", expect_error="E_INVALID_INPUT", check=untouched, method="real-MCP-stdio+direct-COM")

    # ---------------------------------------------------------------- list_layers equals AutoCAD's own view
    def chk_list(p):
        mine = {r["name"].lower(): r for r in cp.all_layer_props(cp.active_doc())}
        theirs = {r["name"].lower(): r for r in p["layers"]}
        must(set(mine) == set(theirs) and p["count"] == len(mine), f"{sorted(mine)} vs {sorted(theirs)}")
        for name, r in theirs.items():
            m = mine[name]
            got = {"on": r["on"], "frozen": r["frozen"], "locked": r["locked"], "color": r["color_index"], "linetype": r["linetype"], "lineweight": r["lineweight"], "plottable": r["plottable"], "name": r["name"]}
            must(same(got, m), f"layer {name}: tool {got} vs direct COM {m}")
        must(p["current_layer"] == cp.retry(lambda: cp.active_doc().ActiveLayer.Name), "current layer differs")
    await case(ctx, "LAY19", "D", "autocad_list_layers", {}, "list_layers equals AutoCAD's own layer table for every layer and every flag (direct COM)", check=chk_list, method="real-MCP-stdio+direct-COM")

    # ---------------------------------------------------------------- entity on a frozen layer survives and is still found
    async def frozen_entity():
        line = await tool(ctx, "autocad_draw_line", {"start_point": [0, 0], "end_point": [10, 0], "layer": LAYER}, label="LAY20-line")
        must(not line["is_error"], short(line["payload"]))
        handle = line["payload"]["handle"]
        fr = await tool(ctx, "autocad_set_layer_properties", {"name": LAYER, "frozen": True}, label="LAY20-freeze")
        must(not fr["is_error"] and fr["payload"]["verified"], short(fr["payload"]))
        ent = cp.entity(cp.active_doc(), handle)
        info = cp.describe(ent)
        must(info["layer"] == LAYER, f"entity layer {info['layer']}")
        lst = await tool(ctx, "autocad_list_entities", {"layers": [LAYER]}, label="LAY20-list")
        must([e["handle"] for e in lst["payload"]["entities"]] == [handle], short(lst["payload"]))
        th = await tool(ctx, "autocad_set_layer_properties", {"name": LAYER, "frozen": False}, label="LAY20-thaw")
        must(not th["is_error"] and th["payload"]["after"]["Freeze"] is False, short(th["payload"]))
        return f"line {handle} stays in model space on the frozen layer and is listed; layer thawed again (Freeze={th['payload']['after']['Freeze']})"
    await acase(ctx, "LAY20", "D", "autocad_set_layer_properties", "an entity on a frozen layer stays in the drawing and in list_entities; thawing restores the layer", frozen_entity, tool_name="autocad_set_layer_properties")


async def main():
    base = cp.baseline()
    print("baseline drawings (never touched):", base)
    async with h.open_session("04_layers", env=h.server_env("com")) as (session, log):
        ctx = Ctx(session, log, "04_layers")
        try:
            await run(ctx, base)
        finally:
            closed = cp.close_new_docs(base)
            print("cleanup closed scratch drawings:", closed)


try:
    asyncio.run(main())
except h.StopRun as exc:
    print("STOPPED:", exc)
    sys.exit(2)
