'''
AssemblyLine: transcriptome meta-assembly from RNA-Seq
Copyright (C) 2012-2015 Matthew Iyer

@author: mkiyer
'''
import collections
import logging

from base import Exon, Strand
from gtf import GTF, GTFError


class Transfrag(object):
    __slots__ = ('chrom', 'strand', 'exons', '_id', 'sample_id', 'expr',
                 'is_ref')

    def __init__(self, chrom=None, strand=None, _id=None, sample_id=None,
                 expr=0.0, is_ref=False, exons=None):
        self.chrom = chrom
        self.strand = Strand.NA if strand is None else strand
        self._id = _id
        self.sample_id = sample_id
        self.expr = expr
        self.is_ref = is_ref
        self.exons = [] if exons is None else exons

    @property
    def length(self):
        return sum((e.end - e.start) for e in self.exons)

    @property
    def start(self):
        return self.exons[0].start

    @property
    def end(self):
        return self.exons[-1].end

    def iterintrons(self):
        #e1 = self.exons[0]
        #for e2 in self.exons[1:]:
        #    yield (e1.end,e2.start)
        #    e1 = e2
        e1 = self.exons[0]
        for j in xrange(1, len(self.exons)):
            e2 = self.exons[j]
            yield e1.end, e2.start
            e1 = e2

    @staticmethod
    def from_gtf(f):
        '''GTF.Feature object to Transfrag'''
        return Transfrag(chrom=f.seqid,
                         strand=Strand.from_gtf(f.strand),
                         _id=f.attrs[GTF.Attr.TRANSCRIPT_ID],
                         sample_id=f.attrs.get(GTF.Attr.SAMPLE_ID, None),
                         expr=float(f.attrs.get(GTF.Attr.EXPRESSION, 0.0)),
                         is_ref=bool(int(f.attrs.get(GTF.Attr.REF, '0'))),
                         exons=None)

    @staticmethod
    def parse_gtf(gtf_lines, ignore_ref=True):
        '''
        returns OrderedDict key is transcript_id value is Transfrag
        '''
        t_dict = collections.OrderedDict()
        for gtf_line in gtf_lines:
            f = GTF.Feature.from_str(gtf_line)
            t_id = f.attrs[GTF.Attr.TRANSCRIPT_ID]
            is_ref = bool(int(f.attrs.get(GTF.Attr.REF, '0')))

            if is_ref and ignore_ref:
                continue

            if f.feature == 'transcript':
                if t_id in t_dict:
                    raise GTFError("Transcript '%s' duplicate detected" % t_id)
                t = Transfrag.from_gtf(f)
                t_dict[t_id] = t
            elif f.feature == 'exon':
                if t_id not in t_dict:
                    logging.error('Feature: "%s"' % str(f))
                    raise GTFError("Transcript '%s' exon feature appeared in "
                                   "gtf file prior to transcript feature" %
                                   t_id)
                t = t_dict[t_id]
                t.exons.append(Exon(f.start, f.end))
        return t_dict
