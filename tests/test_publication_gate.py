import unittest
from src.publication_gate import evaluate
class PublicationGateTests(unittest.TestCase):
    def test_no_human_approval(self):
        r=evaluate({'source':'diba_bibliotecas','kind':'single','eligibility':'review'},{})
        self.assertFalse(r['can_publish']);self.assertIn('HUMAN_APPROVAL_REQUIRED',r['blockers'])
    def test_guia_rights_not_satisfied(self):
        a={'source':'guiabcn','kind':'single','eligibility':'review'}
        b={'date':'2026-10-27','time':'17:30','venue_status':'verified','primary_evidence_status':'verified','primary_evidence_url':'https://guia.barcelona.cat/ca/','attribution':'Guia BCN','source_checked_on':'2026-10-10','price_label':'unknown'}
        r=evaluate(a,b,human_approved=True)
        self.assertIn('SOURCE_REUSE_NOT_RESOLVED',r['blockers'])
    def test_price_unknown_does_not_mean_free(self):
        a={'source':'diba_turismo','kind':'single','eligibility':'review'}
        b={'date':'2026-10-22','time':'18:30','venue_status':'verified','primary_evidence_status':'verified','primary_evidence_url':'https://www.cccb.org/ca/','attribution':'Diputació de Barcelona','source_checked_on':'2026-10-10','price_label':'unknown'}
        self.assertTrue(evaluate(a,b,human_approved=True)['can_publish'])
        b['price_label']='free'
        self.assertIn('FREE_PRICE_UNVERIFIED',evaluate(a,b,human_approved=True)['blockers'])
    def test_image_rights(self):
        a={'source':'generalitat','kind':'single','eligibility':'review'}
        b={'date':'2026-10-20','time':'19:00','venue_status':'verified','primary_evidence_status':'verified','primary_evidence_url':'https://example.org/','attribution':'Generalitat','source_checked_on':'2026-10-10','image_used':True}
        self.assertIn('THIRD_PARTY_IMAGE_RIGHTS_NOT_VERIFIED',evaluate(a,b,human_approved=True)['blockers'])
if __name__=='__main__':unittest.main()
