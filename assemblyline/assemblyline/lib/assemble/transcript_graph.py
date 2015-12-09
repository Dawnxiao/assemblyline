'''
Created on Dec 17, 2011

@author: mkiyer

AssemblyLine: transcriptome meta-assembly from RNA-Seq

Copyright (C) 2012 Matthew Iyer

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''
import networkx as nx
import logging
import collections
import operator
import bisect

from assemblyline.lib.bx.cluster import ClusterTree
from assemblyline.lib.transcript import Exon, POS_STRAND, NEG_STRAND, NO_STRAND
from assemblyline.lib.base import GTFAttr, FLOAT_PRECISION
from base import NODE_SCORE, NODE_LENGTH
from trim import trim_graph
from collapse import collapse_strand_specific_graph

def find_exon_boundaries(transcripts):
    '''
    input: a list of transcripts (not Node objects, these are transcripts)
    parsed directly from an input file and not added to an isoform graph
    yet.

    output: sorted list of exon boundaries
    '''
    exon_boundaries = set()
    # first add introns to the graph and keep track of
    # all intron boundaries
    for transcript in transcripts:
        # add transcript exon boundaries
        for exon in transcript.exons:
            # keep track of positions where introns can be joined to exons
            exon_boundaries.add(exon.start)
            exon_boundaries.add(exon.end)
    # sort the intron boundary positions and add them to interval trees
    return sorted(exon_boundaries)

def split_exon(exon, boundaries):
    """
    partition the exon given list of node boundaries

    generator yields (start,end) intervals for exon
    """
    if exon.start == exon.end:
        return
    # find the indexes into the intron boundaries list that
    # border the exon.  all the indexes in between these two
    # are overlapping the exon and we must use them to break
    # the exon into pieces
    start_ind = bisect.bisect_right(boundaries, exon.start)
    end_ind = bisect.bisect_left(boundaries, exon.end)
    if start_ind == end_ind:
        yield exon.start, exon.end
    else:
        yield exon.start, boundaries[start_ind]
        for j in xrange(start_ind, end_ind-1):
            yield boundaries[j], boundaries[j+1]
        yield boundaries[end_ind-1], exon.end

def split_exons(t, boundaries):
    # split exons that cross boundaries and to get the
    # nodes in the transcript path
    for exon in t.exons:
        for start,end in split_exon(exon, boundaries):
            yield start, end

def resolve_strand(nodes_iter, node_data):
    # find strand with highest score or strand
    # best supported by reference transcripts
    total_scores = [0.0, 0.0]
    ref_bp = [0, 0]
    for n in nodes_iter:
        length = n[1] - n[0]
        nd = node_data[n]
        scores = nd['scores']
        total_scores[POS_STRAND] += (scores[POS_STRAND] * length)
        total_scores[NEG_STRAND] += (scores[NEG_STRAND] * length)
        ref_strands = nd['ref_strands']
        if ref_strands[POS_STRAND]:
            ref_bp[POS_STRAND] += length
        if ref_strands[NEG_STRAND]:
            ref_bp[NEG_STRAND] += length
    if sum(total_scores) > FLOAT_PRECISION:
        if total_scores[POS_STRAND] >= total_scores[NEG_STRAND]:
            return POS_STRAND
        else:
            return NEG_STRAND
    if sum(ref_bp) > 0:
        if ref_bp[POS_STRAND] >= ref_bp[NEG_STRAND]:
            return POS_STRAND
        else:
            return NEG_STRAND
    return NO_STRAND

def partition_transcripts_by_strand(transcripts):
    """
    uses information from stranded transcripts to infer strand for
    unstranded transcripts
    """
    def add_transcript(t, nodes_iter, transcript_lists, node_data):
        for n in nodes_iter:
            node_data[n]['scores'][t.strand] += t.score
        t_id = t.attrs[GTFAttr.TRANSCRIPT_ID]
        transcript_lists[t.strand].append(t)
    # divide transcripts into independent regions of
    # transcription with a single entry and exit point
    boundaries = find_exon_boundaries(transcripts)
    node_data_func = lambda: {'ref_strands': [False, False],
                              'scores': [0.0, 0.0, 0.0]}
    node_data = collections.defaultdict(node_data_func)
    strand_transcript_lists = [[], [], []]
    strand_ref_transcripts = [[], []]
    unresolved_transcripts = []
    for t in transcripts:
        is_ref = bool(int(t.attrs.get(GTFAttr.REF, "0")))
        if is_ref:
            # label nodes by ref strand
            for n in split_exons(t,boundaries):
                node_data[n]['ref_strands'][t.strand] = True
            strand_ref_transcripts[t.strand].append(t)
        elif t.strand != NO_STRAND:
            add_transcript(t, split_exons(t, boundaries),
                           strand_transcript_lists, node_data)
        else:
            unresolved_transcripts.append(t)
    # resolve unstranded transcripts
    logging.debug("\t\t%d unstranded transcripts" %
                  (len(unresolved_transcripts)))
    # keep track of remaining unresolved nodes
    unresolved_nodes = set()
    if len(unresolved_transcripts) > 0:
        resolved = []
        still_unresolved_transcripts = []
        for t in unresolved_transcripts:
            nodes = list(split_exons(t,boundaries))
            t.strand = resolve_strand(nodes, node_data)
            if t.strand != NO_STRAND:
                resolved.append(t)
            else:
                unresolved_nodes.update(nodes)
                still_unresolved_transcripts.append(t)
        for t in resolved:
            add_transcript(t, split_exons(t, boundaries),
                           strand_transcript_lists, node_data)
        unresolved_transcripts = still_unresolved_transcripts
    if len(unresolved_transcripts) > 0:
        logging.debug("\t\t%d unresolved transcripts" %
                      (len(unresolved_transcripts)))
        # if there are still unresolved transcripts then we can try to
        # extrapolate and assign strand to clusters of nodes at once, as
        # long as some of the nodes have a strand assigned
        # cluster unresolved nodes
        unresolved_nodes = sorted(unresolved_nodes)
        cluster_tree = ClusterTree(0,1)
        for i,n in enumerate(unresolved_nodes):
            cluster_tree.insert(n[0], n[1], i)
        # try to assign strand to clusters of nodes
        node_strand_map = {}
        for start, end, indexes in cluster_tree.getregions():
            nodes = [unresolved_nodes[i] for i in indexes]
            strand = resolve_strand(nodes, node_data)
            for n in nodes:
                node_strand_map[n] = strand
        # for each transcript assign strand to the cluster with
        # the best overlap
        unresolved_count = 0
        for t in unresolved_transcripts:
            strand_bp = [0, 0]
            nodes = list(split_exons(t, boundaries))
            for n in nodes:
                strand = node_strand_map[n]
                if strand != NO_STRAND:
                    strand_bp[strand] += (n[1] - n[0])
            total_strand_bp = sum(strand_bp)
            if total_strand_bp > 0:
                if strand_bp[POS_STRAND] >= strand_bp[NEG_STRAND]:
                    t.strand = POS_STRAND
                else:
                    t.strand = NEG_STRAND
            else:
                unresolved_count += 1
            add_transcript(t, nodes, strand_transcript_lists, node_data)
        logging.debug("\t\tCould not resolve %d transcripts" %
                      (unresolved_count))
        del cluster_tree
    return strand_transcript_lists, strand_ref_transcripts

def create_directed_graph(strand, transcripts):
    '''build strand-specific graph'''
    def add_node_directed(G, n, score):
        """add node to graph"""
        if n not in G:
            G.add_node(n, attr_dict={NODE_LENGTH: (n.end - n.start),
                                     NODE_SCORE: 0.0})
        nd = G.node[n]
        nd[NODE_SCORE] += score
    # initialize transcript graph
    G = nx.DiGraph()
    # find the intron domains of the transcripts
    boundaries = find_exon_boundaries(transcripts)
    # add transcripts
    for t in transcripts:
        # split exons that cross boundaries and get the
        # nodes that made up the transcript
        # TODO: can generate
        nodes = [Exon(start,end) for start,end in split_exons(t, boundaries)]
        if strand == NEG_STRAND:
            nodes.reverse()
        # add nodes/edges to graph
        u = nodes[0]
        add_node_directed(G, u, t.score)
        for i in xrange(1, len(nodes)):
            v = nodes[i]
            add_node_directed(G, v, t.score)
            G.add_edge(u,v)
            u = v
    # set graph attributes
    G.graph['boundaries'] = boundaries
    return G

class TranscriptGraph(object):
    def __init__(self, chrom, strand, Gsub):
        self.chrom = chrom
        self.strand = strand
        self.Gsub = Gsub
        self.partial_paths = None

def create_transcript_graphs(chrom, transcripts,
                             min_trim_length=0,
                             trim_utr_fraction=0.0,
                             trim_intron_fraction=0.0,
                             create_bedgraph=False,
                             bedgraph_filehs=None):

    '''
    generates (graph, strand, transcript_map) tuples with transcript
    graphs
    '''
    def get_bedgraph_lines(chrom, G):
        for n in sorted(G.nodes()):
            if n.start < 0:
                continue
            fields = (chrom, n.start, n.end, G.node[n][NODE_SCORE])
            yield fields
    # partition transcripts by strand and resolve unstranded transcripts
    logging.debug("\tResolving unstranded transcripts")
    strand_transcript_lists, strand_ref_transcripts = \
        partition_transcripts_by_strand(transcripts)
    # create strand-specific graphs using redistributed score
    logging.debug("\tCreating transcript graphs")
    transcript_graphs = []
    for strand, transcript_list in enumerate(strand_transcript_lists):
        # create strand specific transcript graph
        G = create_directed_graph(strand, transcript_list)
        # output bedgraph
        if create_bedgraph:
            for fields in get_bedgraph_lines(chrom, G):
                print >>bedgraph_filehs[strand], '\t'.join(map(str,fields))
        # trim utrs and intron retentions
        trim_nodes = trim_graph(G, strand,
                                min_trim_length,
                                trim_utr_fraction,
                                trim_intron_fraction)
        G.remove_nodes_from(trim_nodes)
        # collapse consecutive nodes in graph
        H, node_chain_map = collapse_strand_specific_graph(G, introns=True)
        # get connected components of graph which represent independent genes
        # unconnected components are considered different genes
        Gsubs = nx.weakly_connected_component_subgraphs(H)
        # add components as separate transcript graphs
        strand_graphs = []
        node_subgraph_map = {}
        for i,Gsub in enumerate(Gsubs):
            for n in Gsub:
                node_subgraph_map[n] = i
            tg = TranscriptGraph(chrom, strand, Gsub)
            tg.partial_paths = collections.defaultdict(lambda: 0.0)
            strand_graphs.append(tg)
        # populate transcript graphs with partial paths
        for t in transcript_list:
            # get original transcript nodes and subtract trimmed nodes
            # convert to collapsed nodes and bin according to subgraph
            # TODO: intronic transcripts may be split into multiple pieces,
            # should we allow this?
            subgraph_node_map = collections.defaultdict(lambda: set())
            for n in split_exons(t, G.graph['boundaries']):
                n = Exon(*n)
                if n in trim_nodes:
                    continue
                cn = node_chain_map[n]
                subgraph_id = node_subgraph_map[cn]
                subgraph_node_map[subgraph_id].add(cn)
            # add transcript node/score pairs to subgraphs
            for subgraph_id, subgraph_nodes in subgraph_node_map.iteritems():
                subgraph_nodes = sorted(subgraph_nodes,
                                        key=operator.attrgetter('start'),
                                        reverse=(strand == NEG_STRAND))
                tg = strand_graphs[subgraph_id]
                tg.partial_paths[tuple(subgraph_nodes)] += t.score
        transcript_graphs.extend(strand_graphs)
    # convert
    for tg in transcript_graphs:
        tg.partial_paths = tg.partial_paths.items()
    return transcript_graphs
