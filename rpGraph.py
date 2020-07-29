import networkx as nx
import logging

from rdkit.Chem import MolFromInchi
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.AllChem import Compute2DCoords
from urllib import parse
from rdkit.Chem import Draw

import drawSvg as draw
import svgutils.transform as sg
import math
import copy
import re
import json

logging.basicConfig()
logging.root.setLevel(logging.NOTSET)
logging.basicConfig(level=logging.NOTSET)

logging.basicConfig(
    level=logging.DEBUG,
    #level=logging.WARNING,
    #level=logging.ERROR,
    format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S',
)



ARROWHEAD = draw.Marker(-0.1, -0.5, 0.9, 0.5, scale=4, orient='auto', id='normal_arrow')
ARROWHEAD.append(draw.Lines(-0.1, -0.5, -0.1, 0.5, 0.9, 0, fill='black', close=True))
ARROWHEAD_FLAT = draw.Marker(-0.1, -0.5, 0.9, 0.5, scale=4, orient=0, id='flat_arrow')
ARROWHEAD_FLAT.append(draw.Lines(-0.1, -0.5, -0.1, 0.5, 0.9, 0, fill='black', close=True))
REV_ARROWHEAD = draw.Marker(-0.1, -0.5, 0.9, 0.5, scale=4, orient=0, id='rev_flat_arrow')
REV_ARROWHEAD.append(draw.Lines(-0.1, -0.5, -0.1, 0.5, 0.9, 0, fill='black', close=True))
ARROWHEAD_COMP_X = 7.0
ARROWHEAD_COMP_Y = 7.0

##
#
#
class rpGraph:
    ##
    #
    #
    def __init__(self, rpsbml, pathway_id='rp_pathway', species_group_id='central_species'):
        self.rpsbml = rpsbml
        self.logger = logging.getLogger(__name__)
        #WARNING: change this to reflect the different debugging levels
        self.logger.debug('Started instance of rpGraph')
        self.pathway_id = pathway_id
        self.species_group_id = species_group_id
        self.G = None
        self.species = None
        self.reactions = None
        self.pathway_id = pathway_id
        self.num_reactions = 0
        self.num_species = 0
        self.cid_cofactors = json.load(open('data/mnx_cofactors.json', 'r'))
        self._makeGraph(pathway_id, species_group_id)


    ##
    #
    #
    def _makeGraph(self, pathway_id='rp_pathway', species_group_id='central_species'):
        self.species = [self.rpsbml.model.getSpecies(i) for i in self.rpsbml.readUniqueRPspecies(pathway_id)]
        groups = self.rpsbml.model.getPlugin('groups')
        central_species = groups.getGroup(species_group_id)
        central_species = [i.getIdRef() for i in central_species.getListOfMembers()]
        rp_pathway = groups.getGroup(pathway_id)
        self.reactions = [self.rpsbml.model.getReaction(i.getIdRef()) for i in rp_pathway.getListOfMembers()]
        self.G = nx.DiGraph(brsynth=self.rpsbml.readBRSYNTHAnnotation(rp_pathway.getAnnotation()))
        #nodes
        for spe in self.species:
            self.num_species += 1
            is_central = False
            if spe.getId() in central_species:
                is_central = True
            self.G.add_node(spe.getId(),
                            type='species',
                            name=spe.getName(),
                            miriam=self.rpsbml.readMIRIAMAnnotation(spe.getAnnotation()),
                            brsynth=self.rpsbml.readBRSYNTHAnnotation(spe.getAnnotation()),
                            central_species=is_central)
            for reac in self.reactions:
                self.num_reactions += 1
            self.G.add_node(reac.getId(),
                    type='reaction',
                    miriam=self.rpsbml.readMIRIAMAnnotation(reac.getAnnotation()),
                    brsynth=self.rpsbml.readBRSYNTHAnnotation(reac.getAnnotation()))
        #edges
        for reaction in self.reactions:
            for reac in reaction.getListOfReactants():
                self.G.add_edge(reac.species,
                        reaction.getId(),
                        stoichio=reac.stoichiometry)
                for prod in reaction.getListOfProducts():
                    self.G.add_edge(reaction.getId(),
                            prod.species,
                            stoichio=reac.stoichiometry)


    ##
    #
    #
    def _onlyConsumedSpecies(self):
        only_consumed_species = []
        for node_name in self.G.nodes():
            node = self.G.node.get(node_name)
            if node['type']=='species':
                if not len(list(self.G.successors(node_name)))==0 and len(list(self.G.predecessors(node_name)))==0:
                    only_consumed_species.append(node_name)
        return only_consumed_species


    ##
    #
    #
    def _onlyConsumedCentralSpecies(self):
        only_consumed_species = []
        for node_name in self.G.nodes():
            node = self.G.node.get(node_name)
            if node['type']=='species':
                if node['central_species']==True:
                    if not len(list(self.G.successors(node_name)))==0 and len(list(self.G.predecessors(node_name)))==0:
                        only_consumed_species.append(node_name)
        return only_consumed_species



    ##
    #
    #
    def _onlyProducedSpecies(self):
        only_produced_species = []
        for node_name in self.G.nodes():
            node = self.G.node.get(node_name)
            if node['type']=='species':
                if len(list(self.G.successors(node_name)))==0 and len(list(self.G.predecessors(node_name)))>0:
                    only_produced_species.append(node_name)
        return only_produced_species


    ##
    #
    #
    def _onlyProducedCentralSpecies(self):
        only_produced_species = []
        for node_name in self.G.nodes():
            node = self.G.node.get(node_name)
            if node['type']=='species':
                if node['central_species']==True:
                    if len(list(self.G.successors(node_name)))==0 and len(list(self.G.predecessors(node_name)))>0:
                        only_produced_species.append(node_name)
        return only_produced_species


    ## 
    #
    # Better than before, however bases itself on the fact that central species do not have multiple predesessors
    # if that is the case then the algorithm will return badly ordered reactions
    #
    def _recursiveReacPredecessors(self, node_name, reac_list):
        self.logger.debug('-------- '+str(node_name)+' --> '+str(reac_list)+' ----------')
        pred_node_list = [i for i in self.G.predecessors(node_name)]
        self.logger.debug(pred_node_list)
        if pred_node_list==[]:
            return reac_list
        for n_n in pred_node_list:
            n = self.G.node.get(n_n)
            if n['type']=='reaction':
                if n_n in reac_list:
                    return reac_list
                else:
                    reac_list.append(n_n)
                    self._recursiveReacPredecessors(n_n, reac_list)
            elif n['type']=='species':
                if n['central_species']==True:
                    self._recursiveReacPredecessors(n_n, reac_list)
                else:
                    return reac_list
        return reac_list


    ## Warning that this search algorithm only works for mono-component reactions
    #
    #
    def orderedRetroReactions(self):
        #Note: may be better to loop tho
        for prod_spe in self._onlyProducedSpecies():
            self.logger.debug('Testing '+str(prod_spe))
            ordered = self._recursiveReacPredecessors(prod_spe, [])
            self.logger.debug(ordered)
            if len(ordered)==self.num_reactions:
                return [i for i in reversed(ordered)]
        self.logger.error('Could not find the full ordered reactions')
        return []



    ###########################################################################
    ########################## DRAW ###########################################
    ###########################################################################


    def getSVG(self):
        ordered_reactions = self.orderedRetroReactions()
        pathway_list = []
        #due to the nature of the drawing algorithm (TODO: change), we need to keep track of the previus central species products
        #and reproduce the same list dimension and find the same id location and the rest None
        prev_products = []
        for reaction_id in ordered_reactions:
            #edges
            to_add = {'reactants_inchi': [],
                      'products_inchi': [],
                      'cofactor_reactants': [],
                      'cofactor_products': []}
            for pred_id in rpgraph.G.predecessors(reaction_id):
                pred = rpgraph.G.node.get(pred_id)
                if pred['type']=='species':
                    if pred['central_species']:
                        if any([i in list(self.mnx_cofactors.keys()) for i in pred['miriam']['metanetx']]):
                            to_add['cofactor_reactants'].append(pred['name'])
                        else:
                            to_add['reactants_inchi'].append(pred['brsynth']['inchi'])
                    else:
                        to_add['cofactor_reactants'].append(pred['name'])
                else:
                    self.logger.warning('The current node is not a species: '+str(pred))
            prev_products = [] #reset the list
            for succ_id in rpgraph.G.successors(reaction_id):
                succ = rpgraph.G.node.get(succ_id)
                if succ['type']=='species':
                    if succ['central_species']:
                        if any([i in list(self.mnx_cofactors.keys()) for i in succ['miriam']['metanetx']]):
                            to_add['cofactor_products'].append(succ['name'])
                        else:
                            to_add['products_inchi'].append(succ['brsynth']['inchi'])
                            prev_products.append(succ['brsynth']['inchi'])
                    else:
                        to_add['cofactor_products'].append(succ['name'])
                else:
                    self.logger.warning('The current node is not a species: '+str(succ))


    ##
    #
    # We do this to keep the proportions between the different molecules
    #
    def drawChemicalList(self, inchi_list, subplot_size=[200, 200]):
        toRet = {}
        inchi_list = list(set(inchi_list))
        list_mol = [MolFromInchi(inchi) for inchi in inchi_list]
        for i in range(len(list_mol)):
            cp_list_mol = copy.deepcopy(list_mol)
            cp_list_mol.pop(i)
            tmp_list_mol = [list_mol[i]]+cp_list_mol
            img = Draw.MolsToGridImage(tmp_list_mol, molsPerRow=1, subImgSize=(subplot_size[0], subplot_size[1]), useSVG=True)
            #add the groups tag with the id's of the reactions -- should have be size width=subplot_size[0] height=subplot_size[1]*len(list_mol)
            bond_0_count = 0
            svg_str = ''
            for line in img.splitlines():
                add_line = True
                m0 = re.findall("(\d+\.\d+)", line)
                if m0:
                    for y in m0:
                        if float(y)>subplot_size[1]:
                            add_line = False
                m1 = re.findall("height=\'\d+", line)
                if m1:
                    line = re.sub(r"height=\'\d+", "height=\'"+str(subplot_size[1]), line)
                    #line.replace(str(subplot_size[i]*len(list_mol)), str(subplot_size[1]))
                if add_line:
                    svg_str += line+'\n'
            toRet[inchi_list[i]] = svg_str
        return toRet


    ##
    #
    # Tree diagram for the reactions
    #
    def drawReactionArrows(self, mol_list, left_to_right=True, gap_size=100, subplot_size=[200, 200], stroke_color='black', stroke_width=2):
        x_len = gap_size
        y_len = len(mol_list)*subplot_size[1]
        d = draw.Drawing(x_len, y_len, origin=(0,0))
        self.logger.debug('############ drawReactionArrows ##########')
        self.logger.debug('x_len: '+str(x_len))
        self.logger.debug('y_len: '+str(y_len))
        #white rectangle
        d.append(draw.Rectangle(0, 0, gap_size+subplot_size[0], len(mol_list)*subplot_size[1], fill='#FFFFFF'))
        self.logger.debug('rectangle: '+str(0)+','+str(0))
        self.logger.debug('rectangle: '+str(gap_size+subplot_size[0])+','+str(len(mol_list)*subplot_size[1]))
        #calculate the y starts of the lines
        if left_to_right:
            x_species = 0
            self.logger.debug('x_species: '+str(x_species))
            y_species = [y_len-(i*subplot_size[1])-(subplot_size[1]/2) for i in range(len(mol_list)) if mol_list[i]]
            #calculate the y end of the lines
            x_reaction = gap_size
            self.logger.debug('x_reaction: '+str(x_reaction))
            y_reaction = subplot_size[1]*len(mol_list)/2
            self.logger.debug('y_reaction: '+str(y_reaction))
            for y_spe in y_species:
                self.logger.debug('y_spe: '+str(y_spe))
                p = draw.Path(stroke=stroke_color, stroke_width=stroke_width, fill='transparent', marker_end=ARROWHEAD_FLAT)
                p.M(x_species, y_spe).C(gap_size+x_species, y_spe,
                        x_species, y_reaction,
                        x_reaction-ARROWHEAD_COMP_X, y_reaction)
                d.append(p)
        else:
            x_species = gap_size
            self.logger.debug('x_species: '+str(x_species))
            y_species = [y_len-(i*subplot_size[1])-(subplot_size[1]/2) for i in range(len(mol_list)) if mol_list[i]]
            #calculate the y end of the lines
            x_reaction = 0
            self.logger.debug('x_reaction: '+str(x_reaction))
            y_reaction = subplot_size[1]*len(mol_list)/2
            self.logger.debug('y_reaction: '+str(y_reaction))
            for y_spe in y_species:
                self.logger.debug('y_spe: '+str(y_spe))
                p = draw.Path(stroke=stroke_color, stroke_width=stroke_width, fill='transparent', marker_start=REV_ARROWHEAD)
                p.M(x_species-ARROWHEAD_COMP_X, y_spe).C(gap_size-x_species, y_spe,
                        x_species, y_reaction,
                        x_reaction, y_reaction)
                d.append(p)
        #d.saveSvg('test_arrow.svg')
        return d.asSvg(), x_len, y_len


    # make sure that inchi_list is ordered in such a way that [1,2,3] -> [1,
    #                                                                     2,
    #                                                                     3]
    #
    #
    def drawPartReaction(self,
                         mol_list,
                         arrow_list,
                         left_to_right=True,
                         gap_size=100,
                         subplot_size=[200, 200],
                         is_inchi=True,
                         draw_mol=True,
                         stroke_color='black',
                         stroke_width=2):
        self.logger.debug('---- drawPartReaction ----')
        assert len(mol_list)==len(arrow_list)
        if draw_mol:
            x_len = subplot_size[0]+gap_size
        else:
            x_len = gap_size
        self.logger.debug('x_len: '+str(x_len))
        y_len = len(mol_list)*subplot_size[1]
        self.logger.debug('y_len: '+str(y_len))
        fig = sg.SVGFigure(str(x_len), str(y_len))
        if is_inchi:
            mol_dict = self.drawChemicalList(mol_list, subplot_size)
            mol_list = [mol_dict[i] for i in mol_list]
        if left_to_right:
            count = 0
            for svg in mol_list:
                if svg:
                    f = sg.fromstring(svg)
                    p = f.getroot()
                    p.moveto(0, subplot_size[1]*count)
                    if draw_mol:
                        fig.append(p)
                count += 1
            lines, arrow_len_x, arrow_len_y = self.drawReactionArrows(arrow_list, left_to_right, gap_size, subplot_size)
            line = sg.fromstring(lines)
            line_p = line.getroot()
            self.logger.debug('Move line x: '+str(subplot_size[0]))
            self.logger.debug('Move line y: '+str(subplot_size[1]*len(mol_list)))
            line_p.moveto(x_len-gap_size, subplot_size[1]*len(mol_list))
            fig.append(line_p)
        else:
            lines, arrow_len_x, arrow_len_y = self.drawReactionArrows(arrow_list, left_to_right, gap_size, subplot_size)
            line = sg.fromstring(lines)
            line_p = line.getroot()
            self.logger.debug('Move line y: '+str(subplot_size[1]*len(mol_list)))
            line_p.moveto(0, subplot_size[1]*len(mol_list))
            fig.append(line_p)
            count = 0
            for svg in mol_list:
                f = sg.fromstring(svg)
                p = f.getroot()
                p.moveto(gap_size, subplot_size[1]*count)
                count += 1
                if draw_mol:
                    fig.append(p)
        return fig.to_str().decode("utf-8"), x_len, y_len


    ## draw the cofactors with a box and a line going through
    #
    #
    def drawCofactors(self,
                      cofactor_reactants,
                      cofactor_products,
                      x_len=100,
                      y_len=200,
                      rec_size_y=20,
                      font_family='sans-serif',
                      font_size=20,
                      font_color='black',
                      stroke_color='black',
                      fill_color='#ddd',
                      stroke_width=2):
        d = draw.Drawing(x_len, y_len, origin=(0,0))
        d.append(draw.Rectangle(0, 0, x_len, y_len, fill='#FFFFFF'))
        #draw the cofactors arrow
        start_line_x = x_len/2
        start_line_y = (y_len/2-rec_size_y)-rec_size_y
        end_line_x = x_len/2
        end_line_y = (y_len/2+rec_size_y)+rec_size_y
        self.logger.debug('start_line_x: '+str(start_line_x))
        self.logger.debug('start_line_y: '+str(start_line_y))
        self.logger.debug('end_line_x: '+str(end_line_x))
        self.logger.debug('end_line_y: '+str(end_line_y))
        if cofactor_reactants or cofactor_products:
            #d.append(draw.Line(start_line_x, start_line_y, end_line_x, end_line_y,
            #                    stroke=stroke_color, stroke_width=stroke_width, fill='none'))
            ### arrowhead ##
            p = draw.Path(stroke=stroke_color, stroke_width=stroke_width, fill='transparent', marker_end=ARROWHEAD)
            p.M(start_line_x, start_line_y).Q(start_line_x-rec_size_y/1.5, y_len/2,
                    end_line_x, end_line_y-ARROWHEAD_COMP_Y)
            d.append(p)
        #Draw the reaction rectangle
        self.logger.debug('react_x1: '+str(0))
        self.logger.debug('react_y1: '+str(y_len/2+rec_size_y))
        react_width = x_len
        react_height = rec_size_y
        self.logger.debug('react_width: '+str(react_width))
        self.logger.debug('react_height: '+str(react_height))
        d.append(draw.Rectangle(0, y_len/2-rec_size_y/2, react_width, react_height, fill=fill_color, stroke_width=stroke_width, stroke=stroke_color))
        #draw the text
        #reactants
        y_shift = 0
        for react in cofactor_reactants:
            self.logger.debug(react)
            x = start_line_x
            y = start_line_y-font_size-y_shift-5
            self.logger.debug('x: '+str(x))
            self.logger.debug('y: '+str(y))
            d.append(draw.Text(react, font_size, x, y, font_family=font_family, center=0, fill=font_color))
            y_shift += font_size
        #product
        y_shift = 0
        for pro in cofactor_products:
            self.logger.debug(react)
            x = end_line_x
            y = end_line_y+y_shift+5
            self.logger.debug('x: '+str(x))
            self.logger.debug('y: '+str(y))
            d.append(draw.Text(pro, font_size, x, y, font_family=font_family, center=0, fill=font_color))
            y_shift += font_size
        return d.asSvg()


    ## Draw a reaction 
    #
    #
    def drawReaction(self,
                     reactants,
                     products,
                     react_arrow=[],
                     pro_arrow=[],
                     cofactor_reactants=[],
                     cofactor_products=[],
                     is_inchi=True,
                     react_arrow_size=100,
                     arrow_gap_size=100,
                     subplot_size=[200, 200],
                     draw_left_mol=True,
                     stroke_color='black',
                     stroke_width=2):
        self.logger.debug('========= drawReaction =========')
        if not react_arrow:
            react_arrow = [True for i in reactants]
        if not pro_arrow:
            pro_arrow = [True for i in products]
        if is_inchi:
            #Need to combine them into single request to keep the same proportions
            inchi_svg_dict = self.drawChemicalList([i for i in reactants if i]+[i for i in products if i], subplot_size)
            svg_left, x_len_left, y_len_left = self.drawPartReaction([inchi_svg_dict[i] for i in reactants],
                                                                     react_arrow,
                                                                     left_to_right=True,
                                                                     gap_size=arrow_gap_size,
                                                                     subplot_size=subplot_size,
                                                                     is_inchi=False,
                                                                     draw_mol=draw_left_mol,
                                                                     stroke_color=stroke_color,
                                                                     stroke_width=stroke_width)
            svg_right, x_len_right, y_len_right = self.drawPartReaction([inchi_svg_dict[i] for i in products],
                                                                        pro_arrow,
                                                                        left_to_right=False,
                                                                        gap_size=arrow_gap_size,
                                                                        subplot_size=subplot_size,
                                                                        is_inchi=False,
                                                                        draw_mol=True,
                                                                        stroke_color=stroke_color,
                                                                        stroke_width=stroke_width)
        else:
            svg_left, x_len_left, y_len_left = self.drawPartReaction(reactants,
                                                                     react_arrow,
                                                                     left_to_right=True,
                                                                     gap_size=arrow_gap_size,
                                                                     subplot_size=subplot_size,
                                                                     is_inchi=False,
                                                                     draw_mol=draw_left_mol,
                                                                     stroke_color=stroke_color,
                                                                     stroke_width=stroke_width)
            svg_right, x_len_right, y_len_right = self.drawPartReaction(products,
                                                                        pro_arrow,
                                                                        left_to_right=False,
                                                                        gap_size=arrow_gap_size,
                                                                        subplot_size=subplot_size,
                                                                        is_inchi=False,
                                                                        draw_mol=True,
                                                                        stroke_color=stroke_color,
                                                                        stroke_width=stroke_width)
        self.logger.debug('x_len_left: '+str(x_len_left))
        self.logger.debug('y_len_left: '+str(y_len_left))
        self.logger.debug('x_len_right: '+str(x_len_right))
        self.logger.debug('y_len_right: '+str(y_len_right))
        y_len = 0
        if y_len_left>y_len_right:
            y_len = y_len_left
        else:
            y_len = y_len_right
        x_len = x_len_left+x_len_right+react_arrow_size
        self.logger.debug('x_len: '+str(x_len))
        self.logger.debug('y_len: '+str(y_len))
        #create the final svg
        fig = sg.SVGFigure(str(x_len), str(y_len))
        f_left = sg.fromstring(svg_left)
        p_left = f_left.getroot()
        p_left.moveto(0, (y_len-y_len_left)/2)
        fig.append(p_left)
        f_right = sg.fromstring(svg_right)
        p_right = f_right.getroot()
        p_right.moveto(x_len_left+react_arrow_size, (y_len-y_len_right)/2)
        fig.append(p_right)
        co_reac_svg = self.drawCofactors(cofactor_reactants,
                                        cofactor_products,
                                        x_len=react_arrow_size,
                                        y_len=y_len)
        self.logger.debug(co_reac_svg)
        f_rect = sg.fromstring(co_reac_svg)
        p_rect = f_rect.getroot()
        #300, 500
        p_rect.moveto(x_len_left, y_len)
        fig.append(p_rect)
        return fig.to_str().decode("utf-8"), x_len, y_len

    ##
    #
    # pathway_list: List of dict where each entry contains a list of reaction inchi, with None for positions and
    """
    EXAMPLE:
pathway = [{'reactants_inchi': ['InChI=1S/C10H13N5O3/c11-9-8-10(13-3-12-9)15(4-14-8)7-1-5(17)6(2-16)18-7/h3-7,16-17H,1-2H2,(H2,11,12,13)/t5-,6+,7+/m0/s1'],
            'products_inchi': ['InChI=1S/C6H6O2/c7-5-3-1-2-4-6(5)8/h1-4,7-8H', 'InChI=1S/C6H6O4/c7-5(8)3-1-2-4-6(9)10/h1-4H,(H,7,8)(H,9,10)/b3-1+,4-2+', 'InChI=1S/C3H6O/c1-3(2)4/h1-2H3']
           },
           {'reactants_inchi': ['InChI=1S/C6H6O2/c7-5-3-1-2-4-6(5)8/h1-4,7-8H', None, 'InChI=1S/C3H6O/c1-3(2)4/h1-2H3'],
            'products_inchi': ['InChI=1S/C3H6O/c1-3(2)4/h1-2H3']
           },
           {'reactants_inchi': ['InChI=1S/C3H6O/c1-3(2)4/h1-2H3'],
            'products_inchi': ['InChI=1S/C3H6O/c1-3(2)4/h1-2H3/i1+1,2+1', 'InChI=1S/C3H5O.Zn/c1-3(2)4;/h1H2,2H3;/q-1;']
           }
          ]
    """
    def drawPathway(self,
                    pathway_list,
                    react_arrow_size=100,
                    arrow_gap_size=100,
                    subplot_size=[200, 200],
                    stroke_color='black',
                    stroke_width=2):
        self.logger.debug('________ drawPathway ________')
        #Need to make single command to keep all in the same proportions
        all_inchis = []
        for reaction in pathway_list:
            for inchi in reaction['reactants_inchi']+reaction['products_inchi']:
                if inchi:
                    all_inchis.append(inchi)
        inchi_svg_dict = self.drawChemicalList(all_inchis, subplot_size)
        is_first = True
        pathway_svgs = []
        count = 0
        prev_inchi = []
        for reaction in pathway_list:
            self.logger.debug('count: '+str(count))
            if count==0: #first reaction
                react_inchi = [i for i in reaction['reactants_inchi']]
                react_arrow = [True for i in reaction['reactants_inchi']]
                #combine the current products with the next reactants
                prev_inchi = list(set([i for i in reaction['products_inchi']]+pathway_list[count+1]['products_inchi']))
                pro_inchi = prev_inchi
                pro_arrow = [True if i in reaction['products_inchi'] else False for i in pro_inchi]
            elif count==len(pathway_list)-1: #last reaction
                react_inchi = [i for i in prev_inchi]
                react_arrow = [True if i in reaction['reactants_inchi'] else False for i in react_inchi]
                pro_inchi = reaction['products_inchi']
                pro_arrow = [True for i in reaction['products_inchi']]
            else: #middle
                react_inchi = [i for i in prev_inchi]
                ''' this should be unessecary since the previous reaction had all the inchi mashed together
                for inchi in reaction['reactants_inchi']:
                    if not inchi in react_inchi:
                        react_inchi.append(inchi)
                '''
                react_arrow = [True if i in reaction['reactants_inchi'] else False for i in react_inchi]
                #combine the current products with the next reactants
                prev_inchi = list(set([i for i in reaction['products_inchi']]+pathway_list[count+1]['products_inchi']))
                pro_inchi = prev_inchi
                pro_arrow = [True if i in reaction['products_inchi'] else False for i in pro_inchi]
            self.logger.debug('react_inchi: '+str(react_inchi))
            self.logger.debug('react_arrow: '+str(react_arrow))
            self.logger.debug('pro_inchi: '+str(react_inchi))
            self.logger.debug('pro_arrow: '+str(react_arrow))
            svg, x_len, y_len = self.drawReaction([inchi_svg_dict[i] for i in react_inchi],
                                                  [inchi_svg_dict[i] for i in pro_inchi],
                                                  react_arrow=react_arrow,
                                                  pro_arrow=pro_arrow,
                                                  is_inchi=False,
                                                  cofactor_reactants=reaction['cofactor_reactants'],
                                                  cofactor_products=reaction['cofactor_products'],
                                                  react_arrow_size=react_arrow_size,
                                                  arrow_gap_size=arrow_gap_size,
                                                  subplot_size=subplot_size,
                                                  draw_left_mol=is_first,
                                                  stroke_color=stroke_color,
                                                  stroke_width=stroke_width)
            pathway_svgs.append({'svg': svg, 'x_len': x_len, 'y_len': y_len})
            if is_first:
                is_first = False
            count += 1




        """
        for reaction in pathway_list:
            #need to combine the inchis of the products and reactants of 
            #make the arrows True False list 
            react_arrow = []
            if not prev_products:
                react_inci = [inchi_svg_dict[i] if i else None for i in reaction['reactants_inchi']]
            pro_arrow = []
            pro_inchi = []
            svg, x_len, y_len = self.drawReaction([inchi_svg_dict[i] if i else None for i in reaction['reactants_inchi']],
                                                  [inchi_svg_dict[i] if i else None for i in reaction['products_inchi']],
                                                  is_inchi=False,
                                                  cofactor_reactants=reaction['cofactor_reactants'],
                                                  cofactor_products=reaction['cofactor_products'],
                                                  react_arrow_size=react_arrow_size,
                                                  arrow_gap_size=arrow_gap_size,
                                                  subplot_size=subplot_size,
                                                  draw_left_mol=is_first,
                                                  stroke_color=stroke_color,
                                                  stroke_width=stroke_width)
            pathway_svgs.append({'svg': svg, 'x_len': x_len, 'y_len': y_len})
            if is_first:
                is_first = False
            """
        y_len = 0
        x_len = 0
        for reaction_svg in pathway_svgs:
            x_len += reaction_svg['x_len']
            if reaction_svg['y_len']>y_len:
                y_len = reaction_svg['y_len']
        self.logger.debug('x_len: '+str(x_len))
        self.logger.debug('y_len: '+str(y_len))
        #create the final svg
        fig = sg.SVGFigure(str(x_len), str(y_len))
        cum_x_len = 0
        for reaction_svg in pathway_svgs:
            f = sg.fromstring(reaction_svg['svg'])
            p = f.getroot()
            p.moveto(cum_x_len, (y_len-reaction_svg['y_len'])/2)
            self.logger.debug('cum_x_len: '+str(cum_x_len))
            cum_x_len += reaction_svg['x_len']
            fig.append(p)
        return fig.to_str().decode("utf-8"), pathway_svgs, x_len, y_len


    ################################################# BELOW IS DEV ################################

    """
    def orderedRetroReac(self):
        for node_name in self.G.nodes:
            node = self.G.nodes.get(node_name)
            if node['type']=='reaction':
                self.logger.debug('---> Starting reaction: '+str(node_name))
                tmp_retrolist = [node_name]
                is_not_end_reac = True
                while is_not_end_reac:
                    tmp_spereacs = []
                    #for all the species, gather the ones that are not valid
                    for spe_name in self.G.predecessors(tmp_retrolist[-1]):
                        spe_node = self.G.nodes.get(spe_name)
                        if spe_node['type']=='reaction':
                            self.logger.warning('Reaction '+str(tmp_retrolist[-1])+' is directly connected to the following reaction '+str(spe_name))
                            continue
                        elif spe_node['type']=='species':
                            if spe_node['central_species']==True:
                                self.logger.debug('\tSpecies: '+str(spe_name))
                                self.logger.debug('\t'+str([i for i in self.G.predecessors(spe_name)]))
                                tmp_spereacs.append([i for i in self.G.predecessors(spe_name)])
                        else:
                            self.logger.warning('Node type should be either reaction or species: '+str(node['type']))
                    #remove empty lists
                    self.logger.debug(tmp_spereacs)
                    tmp_spereacs = [i for i in tmp_spereacs if i != []]
                    self.logger.debug(tmp_spereacs)
                    #return the number of same intersect
                    if tmp_spereacs==[]:
                        is_not_end_reac = False
                        continue
                    tmp_spereacs = list(set.intersection(*map(set, tmp_spereacs)))
                    self.logger.debug(tmp_spereacs)
                    if len(tmp_spereacs)>1:     
                        self.logger.warning('There are multiple matches: '+str(tmp_spereacs))
                    elif len(tmp_spereacs)==0:
                        self.logger.debug('Found the last reaction')
                        is_not_end_reac = False
                    elif len(tmp_spereacs)==1:
                        self.logger.debug('Found the next reaction: '+str(tmp_spereacs[0]))
                        if tmp_spereacs[0] not in tmp_retrolist:
                            tmp_retrolist.append(tmp_spereacs[0])
                        else:
                            self.logger.warning('Trying to add a reaction in the sequence that already exists')
                            is_not_end_reac = False
                    self.logger.debug(tmp_retrolist)
                self.logger.debug('The tmp result is: '+str(tmp_retrolist))
                if len(tmp_retrolist)==self.num_reactions:
                    return tmp_retrolist


    def orderedReac(self):
        for node_name in self.G.nodes:
            node = self.G.nodes.get(node_name)
            if node['type']=='reaction':
                self.logger.debug('---> Starting reaction: '+str(node_name))
                tmp_retrolist = [node_name]
                is_not_end_reac = True
                while is_not_end_reac:
                    tmp_spereacs = []
                    #for all the species, gather the ones that are not valid
                    for spe_name in self.G.successors(tmp_retrolist[-1]):
                        spe_node = self.G.nodes.get(spe_name)
                        if spe_node['type']=='reaction':
                            self.logger.warning('Reaction '+str(tmp_retrolist[-1])+' is directly connected to the following reaction '+str(spe_name))
                            continue
                        elif spe_node['type']=='species':
                            if spe_node['central_species']==True:
                                self.logger.debug('\tSpecies: '+str(spe_name))
                                self.logger.debug('\t'+str([i for i in self.G.successors(spe_name)]))
                                tmp_spereacs.append([i for i in self.G.successors(spe_name)])
                        else:
                            self.logger.warning('Node type should be either reaction or species: '+str(node['type']))
                    #remove empty lists
                    self.logger.debug(tmp_spereacs)
                    tmp_spereacs = [i for i in tmp_spereacs if i!=[]]
                    self.logger.debug(tmp_spereacs)
                    #return the number of same intersect
                    if tmp_spereacs==[]:
                        is_not_end_reac = False
                        continue
                    tmp_spereacs = list(set.intersection(*map(set, tmp_spereacs)))
                    self.logger.debug(tmp_spereacs)
                    if len(tmp_spereacs)>1:     
                        self.logger.warning('There are multiple matches: '+str(tmp_spereacs))
                    elif len(tmp_spereacs)==0:
                        self.logger.debug('Found the last reaction')
                        is_not_end_reac = False
                    elif len(tmp_spereacs)==1:
                        self.logger.debug('Found the next reaction: '+str(tmp_spereacs[0]))
                        if tmp_spereacs[0] not in tmp_retrolist:
                            tmp_retrolist.append(tmp_spereacs[0])
                        else:
                            self.logger.warning('Trying to add a reaction in the sequence that already exists')
                            is_not_end_reac = False
                    self.logger.debug(tmp_retrolist)
                self.logger.debug('The tmp result is: '+str(tmp_retrolist))
                if len(tmp_retrolist)==self.num_reactions:
                    return tmp_retrolist
        """
