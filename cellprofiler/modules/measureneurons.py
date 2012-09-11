'''<b>Measure Neurons</b> measures branching information for neurons or
any skeleton objects with seed points
<hr>

<p>This module measures the number of trunks and branches for each neuron in
an image. The module takes a skeletonized image of the neuron plus previously 
identified seed objects (for instance, the neuron soma) and finds the number of 
axon or dendrite trunks that emerge from the soma and the number of branches along the
axons and dendrites.</p>

<p>The module determines distances from the seed objects along the axons and dendrites 
and assigns branchpoints based on distance to the closest seed object when two seed objects
appear to be attached to the same dendrite or axon.</p>

<h4>Available measurements</h4>
<ul>
<li><i>NumberTrunks:</i> The number of trunks. Trunks are branchpoints that lie 
within the seed objects</li>
<li><i>NumberNonTrunkBranches:</i> The number of non-trunk branches. Branches are 
the branchpoints that lie outside the seed objects.</li>
<li><i>NumberBranchEnds</i>: The number of branch end-points, i.e, termini.</li>
</ul>
'''
# CellProfiler is distributed under the GNU General Public License.
# See the accompanying file LICENSE for details.
#
# Copyright (c) 2003-2009 Massachusetts Institute of Technology
# Copyright (c) 2009-2012 Broad Institute
#
# Please see the AUTHORS file for credits.
#
# Website: http://www.cellprofiler.org
#

import numpy as np
from scipy.ndimage import binary_erosion, grey_dilation, grey_erosion
import scipy.ndimage as scind
import os

import cellprofiler.cpimage as cpi
import cellprofiler.cpmodule as cpm
import cellprofiler.objects as cpo
import cellprofiler.measurements as cpmeas
import cellprofiler.settings as cps
import cellprofiler.cpmath.cpmorphology as morph
from cellprofiler.cpmath.cpmorphology import fixup_scipy_ndimage_result as fix
import cellprofiler.cpmath.propagate as propagate
import cellprofiler.preferences as cpprefs

'''The measurement category'''
C_NEURON = "Neuron"

'''The trunk count feature'''
F_NUMBER_TRUNKS = "NumberTrunks"

'''The branch feature'''
F_NUMBER_NON_TRUNK_BRANCHES = "NumberNonTrunkBranches"

'''The endpoint feature'''
F_NUMBER_BRANCH_ENDS = "NumberBranchEnds"

class MeasureNeurons(cpm.CPModule):
    
    module_name = "MeasureNeurons"
    category = "Measurement"
    variable_revision_number = 3
    
    def create_settings(self):
        '''Create the UI settings for the module'''
        self.seed_objects_name = cps.ObjectNameSubscriber(
            "Select the seed objects", "None",
            doc = """Select the previously identified objects that you want to use as the
            seeds for measuring branches and distances. Branches and trunks are assigned
            per seed object. Seed objects are typically not single points/pixels but 
            instead are usually objects of varying sizes.""")
        
        self.image_name = cps.ImageNameSubscriber(
            "Select the skeletonized image", "None",
            doc = """Select the skeletonized image of the dendrites
            and / or axons as produced by the <b>Morph</b> module's
            <i>Skel</i> operation.""")
        
        self.wants_branchpoint_image = cps.Binary(
            "Retain the branchpoint image?", False,
            doc="""Check this setting if you want to save the color image of
            branchpoints and trunks. This is the image that is displayed
            in the output window for this module.""")
        
        self.branchpoint_image_name = cps.ImageNameProvider(
            "Name the branchpoint image","BranchpointImage",
            doc="""
            <i>(Used only if a branchpoint image is to be retained)</i><br>
            Enter a name for the branchpoint image here. You can then 
            use this image in a later module, such as <b>SaveImages</b>.""")
        
        self.wants_to_fill_holes = cps.Binary(
            "Fill small holes?", True,
            doc="""The algorithm reskeletonizes the image and this can leave
            artifacts caused by small holes in the image prior to skeletonizing.
            These holes result in false trunks and branchpoints. Check this
            setting to fill in these small holes prior to skeletonizing.""")
        self.maximum_hole_size = cps.Integer(
            "Maximum hole size:", 10, minval = 1,
            doc = """<i>(Used only when filling small holes)</i><br>This is the area of the largest hole to fill, measured
            in pixels. The algorithm will fill in any hole whose area is
            this size or smaller""")
        self.wants_neuron_graph = cps.Binary(
            "Do you want the neuron graph relationship?", False,
            doc = """Check this setting to produce an edge file and a vertex
            file that give the relationships between trunks, branchpoints
            and vertices""")
        self.intensity_image_name = cps.ImageNameSubscriber(
            "Intensity image:", "None",
            doc = """What is the name of the image to be used to calculate
            the total intensity along the edges between the vertices?""")
        self.directory = cps.DirectoryPath(
            "File output directory:", 
            dir_choices = [
                cps.DEFAULT_OUTPUT_FOLDER_NAME, cps.DEFAULT_INPUT_FOLDER_NAME,
                cps.ABSOLUTE_FOLDER_NAME, cps.DEFAULT_OUTPUT_SUBFOLDER_NAME,
                cps.DEFAULT_INPUT_SUBFOLDER_NAME])
        self.vertex_file_name = cps.Text(
            "Vertex file name: ", "vertices.csv",
            doc = """Enter the name of the file that will hold the edge information.
            You can use metadata tags in the file name. Each line of the file
            is a row of comma-separated values. The first row is the header;
            this names the file's columns. Each subsequent row represents
            a vertex in the neuron skeleton graph: either a trunk, 
            a branchpoint or an endpoint.
            The file has the following columns:
            <br><ul>
            <li><i>image_number</i> : the image number of the associated image</li>
            <li><i>vertex_number</i> : the number of the vertex within the image</li>
            <li><i>i</i> : The I coordinate of the vertex.</li>
            <li><i>j</i> : The J coordinate of the vertex.</li>
            <li><i>label</i> : The label of the seed object associated with
            the vertex.</li>
            <li><i>kind</i> : The kind of vertex it is.
            <ul><li><b>T</b>: trunk</li>
            <li><b>B</b>: branchpoint</li>
            <li><b>E</b>: endpoint</li></ul></li></ul>
            """)
        self.edge_file_name = cps.Text(
            "Edge file name:", "edges.csv",
            doc="""Enter the name of the file that will hold the edge information.
            You can use metadata tags in the file name. Each line of the file
            is a row of comma-separated values. The first row is the header;
            this names the file's columns. Each subsequent row represents
            an edge or connection between two vertices (including between
            a vertex and itself for certain loops).
            The file has the following columns:
            <br><ul>
            <li><i>image_number</i> : the image number of the associated image</li>
            <li><i>v1</i> : The zero-based index into the vertex
            table of the first vertex in the edge.</li>
            <li><i>v2</i> : The zero-based index into the vertex table of the
            second vertex in the edge.</li>
            <li><i>length</i> : The number of pixels in the path connecting the
            two vertices, including both vertex pixels</li>
            <li><i>total_intensity</i> : The sum of the intensities of the
            pixels in the edge, including both vertex pixel intensities.</li>
            </ul>
            """)
    
    def settings(self):
        '''The settings, in the order that they are saved in the pipeline'''
        return [self.seed_objects_name, self.image_name,
                self.wants_branchpoint_image, self.branchpoint_image_name,
                self.wants_branchpoint_image, self.maximum_hole_size,
                self.wants_neuron_graph, self.intensity_image_name,
                self.directory, self.vertex_file_name, self.edge_file_name]
    
    def visible_settings(self):
        '''The settings that are displayed in the GUI'''
        result = [self.seed_objects_name, self.image_name,
                  self.wants_branchpoint_image]
        if self.wants_branchpoint_image:
            result += [self.branchpoint_image_name]
        result += [self.wants_to_fill_holes]
        if self.wants_to_fill_holes:
            result += [self.maximum_hole_size]
        result += [self.wants_neuron_graph]
        if self.wants_neuron_graph:
            result += [self.intensity_image_name, self.directory,
                       self.vertex_file_name, self.edge_file_name]
        return result
    
    def run(self, workspace):
        '''Run the module on the image set'''
        seed_objects_name = self.seed_objects_name.value
        skeleton_name = self.image_name.value
        seed_objects = workspace.object_set.get_objects(seed_objects_name)
        labels = seed_objects.segmented
        labels_count = np.max(labels)
        label_range = np.arange(labels_count,dtype=np.int32)+1
        
        skeleton_image = workspace.image_set.get_image(
            skeleton_name, must_be_binary = True)
        skeleton = skeleton_image.pixel_data
        if skeleton_image.has_mask:
            skeleton = skeleton & skeleton_image.mask
        try:
            labels = skeleton_image.crop_image_similarly(labels)
        except:
            labels, m1 = cpo.size_similarly(skeleton, labels)
            labels[~m1] = 0
        #
        # The following code makes a ring around the seed objects with
        # the skeleton trunks sticking out of it.
        #
        # Create a new skeleton with holes at the seed objects
        # First combine the seed objects with the skeleton so
        # that the skeleton trunks come out of the seed objects.
        #
        # Erode the labels once so that all of the trunk branchpoints
        # will be within the labels
        #
        #
        # Dilate the objects, then subtract them to make a ring
        #
        my_disk = morph.strel_disk(1.5).astype(int)
        dilated_labels = grey_dilation(labels, footprint=my_disk)
        seed_mask = dilated_labels > 0
        combined_skel = skeleton | seed_mask
        
        closed_labels = grey_erosion(dilated_labels,
                                     footprint = my_disk)
        seed_center = closed_labels > 0
        combined_skel = combined_skel & (~seed_center)
        #
        # Fill in single holes (but not a one-pixel hole made by
        # a one-pixel image)
        #
        if self.wants_to_fill_holes:
            def size_fn(area, is_object):
                return (~ is_object) and (area <= self.maximum_hole_size.value)
            combined_skel = morph.fill_labeled_holes(
                combined_skel, ~seed_center, size_fn)
        #
        # Reskeletonize to make true branchpoints at the ring boundaries
        #
        combined_skel = morph.skeletonize(combined_skel)
        #
        # The skeleton outside of the labels
        #
        outside_skel = combined_skel & (dilated_labels == 0)
        #
        # Associate all skeleton points with seed objects
        #
        dlabels, distance_map = propagate.propagate(np.zeros(labels.shape),
                                                    dilated_labels,
                                                    combined_skel, 1)
        #
        # Get rid of any branchpoints not connected to seeds
        #
        combined_skel[dlabels == 0] = False
        #
        # Find the branchpoints
        #
        branch_points = morph.branchpoints(combined_skel)
        #
        # Odd case: when four branches meet like this, branchpoints are not
        # assigned because they are arbitrary. So assign them.
        #
        # .  .
        #  B.
        #  .B
        # .  .
        #
        odd_case = (combined_skel[:-1,:-1] & combined_skel[1:,:-1] &
                    combined_skel[:-1,1:] & combined_skel[1,1])
        branch_points[:-1,:-1][odd_case] = True
        branch_points[1:,1:][odd_case] = True
        #
        # Find the branching counts for the trunks (# of extra branches
        # eminating from a point other than the line it might be on).
        #
        branching_counts = morph.branchings(combined_skel)
        branching_counts = np.array([0,0,0,1,2])[branching_counts]
        #
        # Only take branches within 1 of the outside skeleton
        #
        dilated_skel = scind.binary_dilation(outside_skel, morph.eight_connect)
        branching_counts[~dilated_skel] = 0
        #
        # Find the endpoints
        #
        end_points = morph.endpoints(combined_skel)
        #
        # We use two ranges for classification here:
        # * anything within one pixel of the dilated image is a trunk
        # * anything outside of that range is a branch
        #
        nearby_labels = dlabels.copy()
        nearby_labels[distance_map > 1.5] = 0
        
        outside_labels = dlabels.copy()
        outside_labels[nearby_labels > 0] = 0
        #
        # The trunks are the branchpoints that lie within one pixel of
        # the dilated image.
        #
        if labels_count > 0:
            trunk_counts = fix(scind.sum(branching_counts, nearby_labels, 
                                         label_range)).astype(int)
        else:
            trunk_counts = np.zeros((0,),int)
        #
        # The branches are the branchpoints that lie outside the seed objects
        #
        if labels_count > 0:
            branch_counts = fix(scind.sum(branch_points, outside_labels, 
                                          label_range))
        else:
            branch_counts = np.zeros((0,),int)
        #
        # Save the endpoints
        #
        if labels_count > 0:
            end_counts = fix(scind.sum(end_points, outside_labels, label_range))
        else:
            end_counts = np.zeros((0,), int)
        #
        # Save measurements
        #
        m = workspace.measurements
        assert isinstance(m, cpmeas.Measurements)
        feature = "_".join((C_NEURON, F_NUMBER_TRUNKS, skeleton_name))
        m.add_measurement(seed_objects_name, feature, trunk_counts)
        feature = "_".join((C_NEURON, F_NUMBER_NON_TRUNK_BRANCHES, 
                            skeleton_name))
        m.add_measurement(seed_objects_name, feature, branch_counts)
        feature = "_".join((C_NEURON, F_NUMBER_BRANCH_ENDS, skeleton_name))
        m.add_measurement(seed_objects_name, feature, end_counts)
        #
        # Collect the graph information
        #
        if self.wants_neuron_graph:
            trunk_mask = (branching_counts > 0) & (nearby_labels != 0)
            intensity_image = workspace.image_set.get_image(
                self.intensity_image_name.value)
            edge_graph, vertex_graph = self.make_neuron_graph(
                combined_skel, dlabels, 
                trunk_mask,
                branch_points & ~trunk_mask,
                end_points,
                intensity_image.pixel_data)
            #
            # Add an image number column to both and change vertex index
            # to vertex number (one-based)
            #
            image_number = workspace.measurements.image_set_number
            vertex_graph = np.rec.fromarrays(
                (np.ones(len(vertex_graph)) * image_number,
                 np.arange(1, len(vertex_graph) + 1),
                 vertex_graph['i'],
                 vertex_graph['j'],
                 vertex_graph['labels'],
                 vertex_graph['kind']),
                names = ("image_number", "vertex_number", "i", "j",
                         "labels", "kind"))
            
            edge_graph = np.rec.fromarrays(
                (np.ones(len(edge_graph)) * image_number,
                 edge_graph["v1"],
                 edge_graph["v2"],
                 edge_graph["length"],
                 edge_graph["total_intensity"]),
                names = ("image_number", "v1", "v2", "length", 
                         "total_intensity"))
            
            path = self.directory.get_absolute_path(m)
            edge_file = m.apply_metadata(self.edge_file_name.value)
            edge_path = os.path.abspath(os.path.join(path, edge_file))
            vertex_file = m.apply_metadata(self.vertex_file_name.value)
            vertex_path = os.path.abspath(os.path.join(path, vertex_file))
            d = self.get_dictionary(workspace.image_set_list)
            for file_path, table, fmt in (
                (edge_path, edge_graph, "%d,%d,%d,%d,%.4f"),
                (vertex_path, vertex_graph, "%d,%d,%d,%d,%d,%s")):
                #
                # Delete files first time through / otherwise append
                #
                if not d.has_key(file_path):
                    d[file_path] = True
                    if os.path.exists(file_path):
                        assert False, "Change to use handle_interaction"
                        if self.show_window:
                            import wx
                            if wx.MessageBox(
                                "%s already exists. Do you want to overwrite it?" %
                                file_path, "Warning: overwriting file",
                                style = wx.YES_NO, 
                                parent = workspace.frame) != wx.YES:
                                raise ValueError("Can't overwrite %s" % file_path)
                        os.remove(file_path)
                    fd = open(file_path, 'wt')
                    header = ','.join(table.dtype.names)
                    fd.write(header + '\n')
                else:
                    fd = open(file_path, 'at')
                np.savetxt(fd, table, fmt)
                fd.close()
                if self.show_window:
                    workspace.display_data.edge_graph = edge_graph
                    workspace.display_data.vertex_graph = vertex_graph
        #
        # Make the display image
        #
        if self.show_window or self.wants_branchpoint_image:
            branchpoint_image = np.zeros((skeleton.shape[0],
                                          skeleton.shape[1],
                                          3))
            trunk_mask = (branching_counts > 0) & (nearby_labels != 0)
            branch_mask = branch_points & (outside_labels != 0)
            end_mask = end_points & (outside_labels != 0)
            branchpoint_image[outside_skel,:] = 1
            branchpoint_image[trunk_mask | branch_mask | end_mask,:] = 0
            branchpoint_image[trunk_mask,0] = 1
            branchpoint_image[branch_mask,1] = 1
            branchpoint_image[end_mask, 2] = 1
            branchpoint_image[dilated_labels != 0,:] *= .875
            branchpoint_image[dilated_labels != 0,:] += .1
            if self.show_window:
                workspace.display_data.branchpoint_image = branchpoint_image
            if self.wants_branchpoint_image:
                bi = cpi.Image(branchpoint_image,
                               parent_image = skeleton_image)
                workspace.image_set.add(self.branchpoint_image_name.value, bi)
    
    def display(self, workspace, figure):
        '''Display a visualization of the results'''
        from matplotlib.axes import Axes
        from matplotlib.lines import Line2D
        import matplotlib.cm
        
        if self.wants_neuron_graph:
            figure.set_subplots((2, 1))
        else:
            figure.set_subplots((1, 1))
        title = ("Branchpoints of %s and %s\nTrunks are red\nBranches are green\nEndpoints are blue" %
                 (self.seed_objects_name.value, self.image_name.value))
        figure.subplot_imshow(0, 0, workspace.display_data.branchpoint_image,
                              title)
        if self.wants_neuron_graph:
            image_name = self.intensity_image_name.value
            image = workspace.image_set.get_image(image_name)
            figure.subplot_imshow_grayscale(1, 0, image.pixel_data,
                                            title = "Neuron graph",
                                            sharexy = figure.subplot(0,0))
            axes = figure.subplot(1, 0)
            assert isinstance(axes, Axes)
            edge_graph = workspace.display_data.edge_graph
            vertex_graph = workspace.display_data.vertex_graph
            i = vertex_graph["i"]
            j = vertex_graph["j"]
            kind = vertex_graph["kind"]
            brightness = edge_graph["total_intensity"] / edge_graph["length"]
            brightness = ((brightness - np.min(brightness)) /
                          (np.max(brightness) - np.min(brightness) + .000001))
            cm = matplotlib.cm.get_cmap(cpprefs.get_default_colormap())
            cmap = matplotlib.cm.ScalarMappable(cmap = cm)
            edge_color = cmap.to_rgba(brightness)
            for idx in range(len(edge_graph)):
                v = np.array([edge_graph["v1"][idx] - 1,
                              edge_graph["v2"][idx] - 1])
                line = Line2D(j[v],i[v], color=edge_color[idx])
                axes.add_line(line)
            
    def get_measurement_columns(self, pipeline):
        '''Return database column definitions for measurements made here'''
        return [(self.seed_objects_name.value,
                 "_".join((C_NEURON, feature, self.image_name.value)),
                 cpmeas.COLTYPE_INTEGER)
                for feature in (F_NUMBER_TRUNKS, F_NUMBER_NON_TRUNK_BRANCHES,
                                F_NUMBER_BRANCH_ENDS)]
    
    def get_categories(self, pipeline, object_name):
        '''Get the measurement categories generated by this module
        
        pipeline - pipeline being run
        object_name - name of seed object
        '''
        if object_name == self.seed_objects_name:
            return [ C_NEURON ]
        else:
            return []
        
    def get_measurements(self, pipeline, object_name, category):
        '''Return the measurement features generated by this module
        
        pipeline - pipeline being run
        object_name - object being measured (must be the seed object)
        category - category of measurement (must be C_NEURON)
        '''
        if category == C_NEURON and object_name == self.seed_objects_name:
            return [ F_NUMBER_TRUNKS, F_NUMBER_NON_TRUNK_BRANCHES, 
                     F_NUMBER_BRANCH_ENDS ]
        else:
            return []
        
    def get_measurement_images(self, pipeline, object_name, category, 
                               measurement):
        '''Return the images measured by this module
        
        pipeline - pipeline being run
        object_name - object being measured (must be the seed object)
        category - category of measurement (must be C_NEURON)
        measurement - one of the neuron measurements
        '''
        if measurement in self.get_measurements(pipeline, object_name, 
                                                category):
            return [ self.image_name.value]
        else:
            return []
    
    def upgrade_settings(self, setting_values, variable_revision_number,
                         module_name, from_matlab):
        '''Provide backwards compatibility for old pipelines
        
        setting_values - the strings to be fed to settings
        variable_revision_number - the version number at time of saving
        module_name - name of original module
        from_matlab - true if a matlab pipeline, false if pyCP
        '''
        if from_matlab and variable_revision_number == 1:
            #
            # Added "Wants branchpoint image" and branchpoint image name 
            #
            setting_values = setting_values + [cps.NO, "Branchpoints"]
            from_matlab = False
            variable_revision_number = 1
        if not from_matlab and variable_revision_number == 1:
            #
            # Added hole size questions
            #
            setting_values = setting_values + [cps.YES, "10"]
            variable_revision_number = 2
        if not from_matlab and variable_revision_number == 2:
            #
            # Added graph stuff
            #
            setting_values = setting_values + [ 
                cps.NO, "None", 
                cps.DirectoryPath.static_join_string(cps.DEFAULT_OUTPUT_FOLDER_NAME, "None"),
                "None", "None"]
            variable_revision_number = 3
        return setting_values, variable_revision_number, from_matlab
    
    def make_neuron_graph(self, skeleton, skeleton_labels, 
                          trunks, branchpoints, endpoints, image):
        '''Make a table that captures the graph relationship of the skeleton
        
        skeleton - binary skeleton image + outline of seed objects
        skeleton_labels - labels matrix of skeleton
        trunks - binary image with trunk points as 1
        branchpoints - binary image with branchpoints as 1
        endpoints - binary image with endpoints as 1
        image - image for intensity measurement
        
        returns two tables.
        Table 1: edge table
        The edge table is a numpy record array with the following named
        columns in the following order:
        v1: index into vertex table of first vertex of edge
        v2: index into vertex table of second vertex of edge
        length: # of intermediate pixels + 2 (for two vertices)
        total_intensity: sum of intensities along the edge
        
        Table 2: vertex table
        The vertex table is a numpy record array:
        i: I coordinate of the vertex
        j: J coordinate of the vertex
        label: the vertex's label
        kind: kind of vertex = "T" for trunk, "B" for branchpoint or "E" for endpoint.
        '''
        i,j = np.mgrid[0:skeleton.shape[0], 0:skeleton.shape[1]]
        #
        # Give each point of interest a unique number
        #
        points_of_interest = trunks | branchpoints | endpoints
        number_of_points = np.sum(points_of_interest)
        #
        # Make up the vertex table
        #
        tbe = np.zeros(points_of_interest.shape, '|S1')
        tbe[trunks] = 'T'
        tbe[branchpoints] = 'B'
        tbe[endpoints] = 'E'
        i_idx = i[points_of_interest]
        j_idx = j[points_of_interest]
        poe_labels = skeleton_labels[points_of_interest]
        tbe = tbe[points_of_interest]
        vertex_table = np.rec.fromarrays((i_idx, j_idx, poe_labels, tbe),
                                         names=("i","j","labels","kind"))
        #
        # First, break the skeleton by removing the branchpoints, endpoints
        # and trunks
        #
        broken_skeleton = skeleton & (~points_of_interest)
        #
        # Label the broken skeleton: this labels each edge differently
        #
        edge_labels, nlabels = morph.label_skeleton(skeleton)
        #
        # Reindex after removing the points of interest
        #
        edge_labels[points_of_interest] = 0
        if nlabels > 0:
            indexer = np.arange(nlabels+1)
            unique_labels = np.sort(np.unique(edge_labels))
            nlabels = len(unique_labels)-1
            indexer[unique_labels] = np.arange(len(unique_labels))
            edge_labels = indexer[edge_labels]
            #
            # find magnitudes and lengths for all edges
            #
            magnitudes = fix(scind.sum(image, edge_labels, np.arange(1, nlabels+1,dtype=np.int32)))
            lengths = fix(scind.sum(np.ones(edge_labels.shape),
                                    edge_labels, np.arange(1, nlabels+1,dtype=np.int32))).astype(int)
        else:
            magnitudes = np.zeros(0)
            lengths = np.zeros(0, int)
        #
        # combine the edge labels and indexes of points of interest with padding
        #
        edge_mask = edge_labels != 0
        all_labels = np.zeros(np.array(edge_labels.shape)+2, int)
        all_labels[1:-1,1:-1][edge_mask] = edge_labels[edge_mask] + number_of_points
        all_labels[i_idx+1, j_idx+1] = np.arange(1, number_of_points+1)
        #
        # Collect all 8 neighbors for each point of interest
        #
        p1 = np.zeros(0,int)
        p2 = np.zeros(0,int)
        for i_off, j_off in ((0,0), (0,1), (0,2),
                             (1,0),        (1,2),
                             (2,0), (2,1), (2,2)):
            p1 = np.hstack((p1, np.arange(1, number_of_points+1)))
            p2 = np.hstack((p2, all_labels[i_idx+i_off,j_idx+j_off]))
        #
        # Get rid of zeros which are background
        #
        p1 = p1[p2 != 0]
        p2 = p2[p2 != 0]
        #
        # Find point_of_interest -> point_of_interest connections.
        #
        p1_poi = p1[(p2 <= number_of_points) & (p1 < p2)]
        p2_poi = p2[(p2 <= number_of_points) & (p1 < p2)]
        #
        # Make sure matches are labeled the same
        #
        same_labels = (skeleton_labels[i_idx[p1_poi-1], j_idx[p1_poi-1]] ==
                       skeleton_labels[i_idx[p2_poi-1], j_idx[p2_poi-1]])
        p1_poi = p1_poi[same_labels]
        p2_poi = p2_poi[same_labels]
        #
        # Find point_of_interest -> edge
        #
        p1_edge = p1[p2 > number_of_points]
        edge = p2[p2 > number_of_points]
        #
        # Now, each value that p2_edge takes forms a group and all
        # p1_edge whose p2_edge are connected together by the edge.
        # Possibly they touch each other without the edge, but we will
        # take the minimum distance connecting each pair to throw out
        # the edge.
        #
        edge, p1_edge, p2_edge = morph.pairwise_permutations(edge, p1_edge)
        indexer = edge - number_of_points - 1
        lengths = lengths[indexer]
        magnitudes = magnitudes[indexer]
        #
        # OK, now we make the edge table. First poi<->poi. Length = 2,
        # magnitude = magnitude at each point
        #
        poi_length = np.ones(len(p1_poi)) * 2
        poi_magnitude = (image[i_idx[p1_poi-1], j_idx[p1_poi-1]] +
                         image[i_idx[p2_poi-1], j_idx[p2_poi-1]])
        #
        # Now the edges...
        #
        poi_edge_length = lengths + 2
        poi_edge_magnitude = (image[i_idx[p1_edge-1], j_idx[p1_edge-1]] +
                              image[i_idx[p2_edge-1], j_idx[p2_edge-1]] +
                              magnitudes)
        #
        # Put together the columns
        #
        v1 = np.hstack((p1_poi, p1_edge))
        v2 = np.hstack((p2_poi, p2_edge))
        lengths = np.hstack((poi_length, poi_edge_length))
        magnitudes = np.hstack((poi_magnitude, poi_edge_magnitude))
        #
        # Sort by p1, p2 and length in order to pick the shortest length
        #
        indexer = np.lexsort((lengths, v1, v2))
        v1 = v1[indexer]
        v2 = v2[indexer]
        lengths = lengths[indexer]
        magnitudes = magnitudes[indexer]
        if len(v1) > 0:
            to_keep = np.hstack(([True], 
                                 (v1[1:] != v1[:-1]) | 
                                 (v2[1:] != v2[:-1])))
            v1 = v1[to_keep]
            v2 = v2[to_keep]
            lengths = lengths[to_keep]
            magnitudes = magnitudes[to_keep]
        #
        # Put it all together into a table
        #
        edge_table = np.rec.fromarrays(
            (v1, v2, lengths, magnitudes),
            names = ("v1","v2","length","total_intensity"))
        return edge_table, vertex_table
        
