import copy
import unittest
from mod_recipe import create, apply, sha1

class SourceRecipeTests(unittest.TestCase):
    def setUp(self):
        self.base={"actual":b"0123456789"}
        source={"kind":"base","path":"actual","sha1":sha1(self.base["actual"]),"offset":0,"length":10}
        self.target={"copy":b"0123456789","edited":b"01XY67"}
        self.bindings={
            "copy":{"kind":"derived","sources":[source],"witnesses":[{"generator":"test identity"}]},
            "edited":{"kind":"derived","sources":[{**source,"length":2},{**source,"offset":6,"length":2,"destination":4}],
                      "witnesses":[{"generator":"test edit"}]}
        }

    def test_unchanged_source_copies_store_no_original_payload(self):
        recipe,residuals=create(self.base,self.target,self.bindings)
        self.assertEqual(apply(recipe,residuals,self.base),self.target)
        self.assertEqual(recipe["entries"][0]["writes"],[])
        self.assertNotIn(self.base["actual"],residuals)

    def test_wrong_sources_and_changed_residuals_fail_verification(self):
        recipe,residuals=create(self.base,self.target,self.bindings)
        with self.assertRaisesRegex(ValueError,"source failed"):
            apply(recipe,residuals,{"actual":b"wrong"})
        with self.assertRaisesRegex(ValueError,"recipe or literals"):
            apply(recipe,residuals+b"changed",self.base)
        bad=copy.deepcopy(recipe);bad["entries"][1]["writes"]=[[999,0,1]]
        with self.assertRaisesRegex(ValueError,"patch range"):
            apply(bad,residuals,self.base)

    def test_unreviewed_new_resource_cannot_fall_back_to_full_literals(self):
        with self.assertRaisesRegex(ValueError,"provenance bindings"):
            create(self.base,{**self.target,"unreviewed":b"original material"},self.bindings)

    def test_locally_generated_restoration_sources_support_exact_slices(self):
        model=b"local restoration model";target={"new":b"rest!"}
        sources=[{"kind":"project","path":"restoration-model.bin","sha1":sha1(model),"offset":6,"length":4}]
        bindings={"new":{"kind":"derived","sources":sources,"witnesses":[{"generator":"restoration patch"}]}}
        recipe,residuals=create({},target,bindings,{"restoration-model.bin":model})
        self.assertEqual(apply(recipe,residuals,{},project_sources={"restoration-model.bin":model}),target)
        with self.assertRaisesRegex(ValueError,"source failed"):
            apply(recipe,residuals,{},project_sources={"restoration-model.bin":b"different"})

if __name__=="__main__":
    unittest.main()
