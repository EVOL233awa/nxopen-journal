# -*- coding: utf-8 -*-
# Test D2: modify existing part (open + SetDisplayPart + edge blend + save)
import os
import NXOpen
import NXOpen.Features
import NXOpen.UF

PART_PATH = os.path.abspath("asm_plate.prt")

def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part, status = session.Parts.Open(PART_PATH)
    print("OPEN_OK part=" + str(part.FullPath))
    ufs.Part.SetDisplayPart(part.Tag)
    print("SET_DISPLAY_OK")
    body = [b for b in part.Bodies][0]
    rule = part.ScRuleFactory.CreateRuleEdgeBody(body)
    collector = part.ScCollectors.CreateCollector()
    collector.ReplaceRules([rule], False)
    builder = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    builder.AddChainset(collector, "1.0")
    builder.CommitFeature()
    builder.Destroy()
    collector.Destroy()
    print("EDGE_BLEND_OK")
    ufs.Part.Save()
    print("TEST05_DONE")

if __name__ == "__main__":
    main()