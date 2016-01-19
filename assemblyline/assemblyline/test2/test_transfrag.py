

from assemblyline.lib2.base import Exon, Strand
from assemblyline.lib2.transfrag import Transfrag


def test_introns():
    t = Transfrag(chrom='chrTest', strand=Strand.POS,
                  exons=[Exon(0, 10), Exon(20, 30), Exon(40, 50)])
    introns = list(t.iterintrons())
    assert len(introns) == 2
    assert introns[0] == (10, 20)
    assert introns[1] == (30, 40)
