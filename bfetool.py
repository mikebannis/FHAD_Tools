import arcpy
import collections
import math
import os
import tempfile
import time

BFE_ELEV_FIELD = 'Elevation'
BFE_STA_FIELD = 'Station'
FIELD_LENGTH = 100

BFE = collections.namedtuple('BFE', ['elevation', 'station'])
channel_point = collections.namedtuple('channel_point', ['X','Y','station'])

DEBUG = False
if DEBUG:
    p = arcpy.AddMessage

class BFENotFound(Exception):
    pass
    
class BFE_Locations:
    """ Used to create BFE locations for a reach. This needs to be tested extensively """
    def __init__(self, reach):
        self.reach = reach
    
    def calc_locations(self):
        """ Determine stations for all BFEs on the reach. Returns a list of BFE named 
            tuples sorted in ascending order.
        """
        # print self.reach.river_name, self.reach.reach_name
        # print '-'*50+'\n'
        self.BFEs = []
        cross_sections = self.reach.cross_sections
        self.min_BFE = math.ceil(self.reach.min_WSEL())
        self.max_BFE = math.floor(self.reach.max_WSEL())
        
        for i in range(len(cross_sections)-1):
            self.BFEs += self._calc_BFEs_between_XSs(cross_sections[i], cross_sections[i+1])
        
        self.BFE_checker()
        return self.BFEs
    
    def BFE_checker(self):
        """ Verify that BFE elevation and stations are always increasing and BFEs are 
            integers. This guarantees that there are no duplicates.
        """
        first_lap = True
        for test_BFE in self.BFEs:
            if first_lap:
                last_elevation = test_BFE.elevation
                last_station = test_BFE.station
                first_lap = False
                continue
            assert(last_elevation < test_BFE.elevation)
            assert(last_station < test_BFE.station)
            assert(int(last_elevation) == last_elevation)
            last_elevation = test_BFE.elevation
            last_station = test_BFE.station
        
    def _calc_BFEs_between_XSs(self, XS1, XS2):
        """ Find all BFEs between XS1 and XS2. Checks for negative slopes.
            Returns list of BFE named tuples sorted in ascending order.
        """
        BFEs = []
        # Bail if the water surface slope backwards
        if XS1.WSEL > XS2.WSEL:
            return []
        local_min_BFE = int(math.ceil(XS1.WSEL))
        local_max_BFE = int(math.floor(XS2.WSEL))
        # Loops through all integer elevations between XS1 and XS2
        for current_BFE in range(local_min_BFE, local_max_BFE+1):
            # Only one BFE of a give elevation per reach please
            if not self._BFE_exists(current_BFE):
                station = self._calc_BFE_location(XS1, XS2, current_BFE)
                new_BFE = BFE(elevation=current_BFE, station=station)
                BFEs.append(new_BFE)
        return BFEs
        
    def _calc_BFE_location(self, XS1, XS2, BFE_WSEL):
        """ Returns BFE station between cross sections """
        # print XS1, XS2, BFE_WSEL
        m = (XS2.WSEL - XS1.WSEL)/(XS2.cum_length - XS1.cum_length)
        # This will only occur for integer BFEs at the start of a reach
        if m == 0:
            return XS1.cum_length
        b = XS1.WSEL - m*XS1.cum_length
        # Idiot check
        b_test = XS2.WSEL - m*XS2.cum_length
        assert (round(b,10) == round(b_test,10))
        return (BFE_WSEL - b)/m
    
    def _BFE_exists(self, current_BFE):
        """ Returns true if BFE already exists, else False """
        for test_BFE in self.BFEs:
            if test_BFE.elevation == current_BFE:
                return True
        return False
        
        
class RiverSystem:
    def __init__(self):
        self.reaches = []
        self.sorted = False
        self.reach_lengths_calcd = False
    
    def __repr__(self):
        return_str = ''
        for reach in self.reaches:
            return_str += repr(reach)
        return return_str
    
    def get_reach(self, river_name, reach_name):
        for reach in self.reaches:
            if reach.river_name == river_name and reach.reach_name == reach_name:
                return reach
        else:
            new_reach = Reach(river_name, reach_name)
            self.reaches.append(new_reach)
            return new_reach
    
    def reach_exists(self, river_name, reach_name):
        for reach in self.reaches:
            if reach.river_name == river_name and reach.reach_name == reach_name:
                return True
        else:
            return False
            
    def sort_all(self):
        for reach in self.reaches:
            reach.sort_XS()
        self.sorted = True
            
    ### This appears to be completely unnecessary. Oops.
    def calc_all_reach_lengths(self):
        if self.sorted:
            for reach in self.reaches:
                reach.calc_reach_lengths()
            self.reach_lengths_calcd = True
        else:
            print '*'*20+'Must sort cross sections before '+\
                    'calculating reach lengths!'
            # This is not right but gets the job done
            raise
    
    def number_of_XSs(self):
        total_XS = 0
        for reach in self.reaches:
            total_XS += len(reach.cross_sections)
        return total_XS
    
    def calc_all_BFEs(self):
        if self.reach_lengths_calcd:
            for reach in self.reaches:
                reach.calc_BFEs()
        else:
            print '*'*20+'Must calculate reach lengths '+\
                    'before calculating BFEs!'
            # This is not right but gets the job done
            raise
    
    def number_of_BFEs(self):
        """ Return number of BFEs in all reaches """
        number = 0
        for reach in self.reaches:
            number += len(reach.BFEs)
        return number
          
          
class Reach:
    def __init__(self, river_name, reach_name):
        self.river_name = river_name
        self.reach_name = reach_name
        self.cross_sections = []
        self.BFEs = []
            
    def __repr__(self):
        return_str = self.river_name+', '+self.reach_name+'\n'
        return_str += '-'*50+'\n'
        for xs in self.cross_sections:
            return_str += repr(xs)
        if self.BFEs != []:
            return_str += 'BFEs:\n'
            for current_BFE in self.BFEs:
                return_str += str(current_BFE)+'\n'
        return return_str+'\n'
        
    def add_XS(self, ID, profile, WSEL, cum_length):
        # Correct HEC-RAS pretending the downstream XS has 0 length
        if cum_length == '':
            cum_length = 0.0
        new_XS = CrossSection(ID, profile, WSEL, cum_length)
        self.cross_sections.append(new_XS)
    
    def sort_XS(self):
        self.cross_sections.sort(key=lambda x:x.cum_length)
    
    def calc_reach_lengths(self):
        for i in range(len(self.cross_sections)):
            if i == 0:
                self.cross_sections[0].reach_length = self.cross_sections[0].cum_length
            else:
                self.cross_sections[i].reach_length = self.cross_sections[i].cum_length - \
                        self.cross_sections[i-1].cum_length
        
    def max_WSEL(self):
        max = -1
        for xs in self.cross_sections:
            if xs.WSEL > max:
                max = xs.WSEL
        return max
    
    def min_WSEL(self):
        min = 999999.0
        for xs in self.cross_sections:
            if xs.WSEL < min:
                min = xs.WSEL
        return min
        
    def calc_BFEs(self):
        BFE_loc = BFE_Locations(self)
        self.BFEs = BFE_loc.calc_locations()

        
class CrossSection:
    def __init__(self, ID, profile, WSEL, cum_length):
        self.ID = ID
        self.profile = profile
        self.WSEL = float(WSEL)
        self.cum_length = float(cum_length)
        self.reach_length = -1.0
        
    def __repr__(self):
        return self.ID+', '+self.profile+', '+str(self.WSEL)+', '+\
                str(self.cum_length)+', '+str(self.reach_length)+'\n'    

 
class CreateBFEs(object):
    def __init__(self, rs, channel_filename, channel_river_field, channel_reach_field, outfilename, BFE_length=100):
        self.rs = rs
        self.channel_filename = channel_filename
        self.channel_river_field = channel_river_field
        self.channel_reach_field = channel_reach_field
        self.outfilename = outfilename
        self.BFE_length = BFE_length
        self.BFE_wings = False
        
    def set_BFE_dimensions(self, BFE_length, BFE_wings, BFE_wing_length):
        """ Optional arguments. This finishes __init__ """
        self.BFE_length = BFE_length
        self.BFE_wings = BFE_wings
        self.BFE_wing_length = BFE_wing_length
    
    def create_BFEs(self):
        BFE_points = self._create_BFE_points()
        self._create_BFE_lines(BFE_points)
        self._delete_temp_file(BFE_points)
        
    def _create_BFE_points(self):
        """ Creates temporary shapefile of BFE points. This is step 1 
            Returns temporary shapefile name with full path
        """
        arcpy.SetProgressor("default", "Preparing to create BFEs...")

        # Set up BFE point shape file
        temp_point_file = self._temp_filename()+'.shp'
        self._setup_shapefile(temp_point_file, 'POINT', 'Creating temporary BFE point shapefile: ')
            
        arcpy.SetProgressor("step", "Creating temporary BFE points..." , 0, 100, 10)
        arcpy.AddMessage('Populating temporary BFE points... ')
        try:
            total_BFEs = self.rs.number_of_BFEs()
            BFEs_created = []
            num_BFEs_created = 0
            with arcpy.da.SearchCursor(self.channel_filename, ['SHAPE@', self.channel_river_field, 
                self.channel_reach_field]) as channel_cursor:
                with arcpy.da.InsertCursor(temp_point_file, ['SHAPE@', self.channel_river_field, 
                    self.channel_reach_field, BFE_ELEV_FIELD, BFE_STA_FIELD]) as BFE_cursor:
                    for channel in channel_cursor:
                        # See if we have BFEs for that reach
                        if self.rs.reach_exists(channel[1], channel[2]):
                            current_reach = self.rs.get_reach(channel[1], channel[2])
                        else:
                            continue
                        # Got BFEs, lets make some points!
                        channel_geo = channel[0]
                        for current_BFE in current_reach.BFEs:
                            new_point = channel_geo.positionAlongLine(current_BFE.station, False)
                            BFE_cursor.insertRow([new_point, channel[1], channel[2], current_BFE.elevation, current_BFE.station])

                            #Keep track of created BFEs and update progress bar
                            num_BFEs_created += 1
                            BFEs_created.append(channel[1]+'/'+channel[2]+'/'+str(current_BFE.elevation)+\
                                                '/'+str(current_BFE.station))
                            if num_BFEs_created % (int(total_BFEs/10)) == 0:
                                arcpy.SetProgressorPosition()
        except Exception as detail:
            arcpy.AddError('Error created temporary BFE points: ' + str(detail))
            raise

        arcpy.AddMessage(str(num_BFEs_created)+' BFEs created out of '+str(total_BFEs)+' total BFEs.')
        if num_BFEs_created > total_BFEs:
            arcpy.AddWarning('Warning! More BFEs were created than exist in the input file! Are there duplicate alignments?')
        if num_BFEs_created < total_BFEs:
            arcpy.AddWarning('Warning! Not all BFEs in input file were created!')
        if num_BFEs_created == 0:
            arcpy.AddWarning('Zero BFEs were created. Please verify HEC-RAS table order is Downstream to Upstream (HEC2 Style)')
            
        return (temp_point_file)
        
    def _create_BFE_lines(self, BFE_points):
        """ 
        Creates perpendicular lines at BFE_points to channel alignment.
        This is step 2
        
        BFE_points  -   temporary shapefile of BFEs represented as points
        """
        #Creat output file
        self._setup_shapefile(self.outfilename, 'POLYLINE', 'Creating BFE line shapefile: ')
        
        # Count number of BFEs to make
        arcpy.MakeTableView_management(BFE_points, 'tempTableView')
        total_BFE_count = int(arcpy.GetCount_management('tempTableView').getOutput(0))
        number_BFEs_created = 0
        arcpy.SetProgressor("step", "Creating BFE lines..." , 0, 100, 10)
        arcpy.AddMessage('Creating BFE lines...')
        
        # Loop through all channel alignments
        with arcpy.da.SearchCursor(self.channel_filename, ['SHAPE@', self.channel_river_field, self.channel_reach_field]) as channel_cursor:
            for channel in channel_cursor:
                # Assumes only one part of each alignment, add test for this
                channel_geo = channel[0].getPart(0)
                river_name = channel[1]
                reach_name = channel[2]
                arcpy.AddMessage('Processing river: '+river_name+', reach: '+reach_name+' length: '+str(channel[0].length))
                if channel[0].isMultipart:
                    arcpy.AddWarning('River/reach is a multipart feature. This is likely an error!')
                    
                # Get all points from the channel alignment
                channel_points = self._channel_point_list(channel_geo)

                # Loop through all BFE points and create BFE lines
                with arcpy.da.SearchCursor(BFE_points, ['SHAPE@', BFE_ELEV_FIELD, BFE_STA_FIELD, self.channel_river_field, self.channel_reach_field]) as BFE_pnt_cursor:
                    with arcpy.da.InsertCursor(self.outfilename, ['SHAPE@', BFE_ELEV_FIELD, BFE_STA_FIELD, self.channel_river_field, self.channel_reach_field]) as BFE_line_cursor:
                        for BFE_pnt_feature in BFE_pnt_cursor:
                            # Check if the BFE is for the current river/reach
                            if BFE_pnt_feature[3] == river_name and BFE_pnt_feature[4] == reach_name:
                                BFE_pnt_geo = BFE_pnt_feature[0].firstPoint
                                BFE_elev = BFE_pnt_feature[1]
                                BFE_pnt = channel_point(BFE_pnt_geo.X, BFE_pnt_geo.Y, BFE_pnt_feature[2])
                                if DEBUG:
                                    p(str(BFE_elev)+' '+str(BFE_pnt_feature[2]))
                                # Calculate channel angle at BFE and create BFE polyline
                                try:
                                    new_BFE_polyline = self._calc_BFE_geo(BFE_pnt, channel_points)
                                except BFENotFound:
                                    arcpy.AddWarning('Location of BFE '+str(BFE_pnt_feature[1])+' at station '+str(BFE_pnt_feature[2])+' on '+\
                                                        BFE_pnt_feature[3]+'\\'+BFE_pnt_feature[4]+' not found!')
                                else:
                                    ### Update this protion in the new bfetool.py
                                    # Add to shape file
                                    BFE_line_cursor.insertRow([new_BFE_polyline, BFE_elev, BFE_pnt.station, river_name, reach_name])
                                    number_BFEs_created += 1
                                    if number_BFEs_created % (int(total_BFE_count/10)) == 0:
                                        arcpy.SetProgressorPosition()
        # Check how many BFEs were created
        if number_BFEs_created == total_BFE_count:
            arcpy.AddMessage('Done. '+str(number_BFEs_created)+' BFEs created.')
        else:
            arcpy.AddWarning('Warning: '+str(number_BFEs_created)+' BFEs created instead of '+str(total_BFE_count))

    def _calc_BFE_geo(self, BFE_pnt, channel_points):
        """ Create perpendicular line at BFE_pnt crossing the channel alignment """
        arc_array = arcpy.Array()
        theta = self._find_channel_angle_at_BFE(BFE_pnt, channel_points)
        left_pnt = self._point_at_angle_dist(BFE_pnt, theta+math.pi/2, self.BFE_length/2)
        right_pnt = self._point_at_angle_dist(BFE_pnt, theta-math.pi/2, self.BFE_length/2)
        if self.BFE_wings:
            # Add wings to the BFE to make delineation in CAD faster
            left_left_pnt = self._point_at_angle_dist(left_pnt, theta+math.pi/2, self.BFE_wing_length)
            right_right_pnt = self._point_at_angle_dist(right_pnt, theta-math.pi/2, self.BFE_wing_length)
            arc_array.add(left_left_pnt)
            arc_array.add(left_pnt)
            arc_array.add(right_pnt)
            arc_array.add(right_right_pnt)
            return arcpy.Polyline(arc_array)
        else:
            # Only a two point line
            arc_array.add(left_pnt)
            arc_array.add(right_pnt)
            return arcpy.Polyline(arc_array)

    def _channel_point_list(self, channel_geo):
        """ Returns list of vertices of channel_geo in channel_point format"""
        current_station = 0
        channel_points = []
        first_point = True
        for pnt in channel_geo:
            temp_pnt = channel_point(pnt.X, pnt.Y, 0)
            # Don't calculate channel length at first point
            if first_point:
                first_point = False
            else:
                current_station += self._distance(last_pnt, temp_pnt)
            new_pnt = channel_point(temp_pnt.X, temp_pnt.Y, current_station)
            channel_points.append(new_pnt)
            last_pnt = new_pnt
        return channel_points
            
    def _setup_shapefile(self, filename, shape, message):
        """ Creates output/temp shapefile, adds fields, and updates the arcpy status dialog  """
        try:
            arcpy.AddMessage(message+filename)
            spatial_reference = arcpy.Describe(self.channel_filename).spatialReference
            arcpy.CreateFeatureclass_management(os.path.dirname(filename), os.path.basename(filename), 
                                                    shape, '', '', '', spatial_reference)
            arcpy.AddMessage('Adding fields...')
            arcpy.AddField_management(filename, self.channel_river_field, 'TEXT', field_length = FIELD_LENGTH)
            arcpy.AddField_management(filename, self.channel_reach_field, 'TEXT', field_length = FIELD_LENGTH)
            arcpy.AddField_management(filename, BFE_ELEV_FIELD, 'DOUBLE')
            arcpy.AddField_management(filename, BFE_STA_FIELD, 'DOUBLE')       
        except:
            arcpy.AddError('Unable to create '+filename+'. Is the shape file open in another program or is the workspace being edited?')
            raise
        else:
            arcpy.AddMessage('Done.')
        
    def _temp_filename(self):
        name = tempfile.NamedTemporaryFile(delete=False)
        name.close()
        return name.name
    
    def _delete_temp_file(self, BFE_points):
        arcpy.AddMessage('Deleting temporary BFE point file... ')
        try:
            arcpy.Delete_management(BFE_points)
        except:
            arcpy.AddWarning('Unable to delete temporary file.')
            raise
        else:
            arcpy.AddMessage('Done.')
            
    def _distance(self, pnt1, pnt2):
        """ returns distance between two points via c^2 = a^2 + b^2 """
        csquare = (pnt1.X-pnt2.X)**2+(pnt1.Y-pnt2.Y)**2
        return math.sqrt(csquare)
        
    def _point_at_angle_dist(self, orig_pnt, theta, dist):
        """ Creates new point at angle theta and dist from orig_point """
        arc_point = arcpy.Point()
        arc_point.X = orig_pnt.X + dist*math.cos(theta)
        arc_point.Y = orig_pnt.Y + dist*math.sin(theta)
        return arc_point
    
    def _angle(self, point1, point2):
        """ Returns angle between two points in radians """
        if point2.X == point1.X:
            if point2.Y > point1.Y:
                return math.pi/2
            else:
                return -math.pi/2
        else:
            return math.atan((point2.Y-point1.Y)/(point2.X-point1.X))
            
    def _find_channel_angle_at_BFE(self, BFE_pnt, channel_points):
            """ Returns the angle of the channel at the BFE point """
            num_chnl_pts = len(channel_points)
            # See if BFE is between two channel vertices
            for i in range(num_chnl_pts-1):
                if channel_points[i].station < BFE_pnt.station and BFE_pnt.station < channel_points[i+1].station:
                        return self._angle(channel_points[i], channel_points[i+1])
            # Not between vertices, see if its on a vertex
            ####### This is not yet tested!!! #####################
            for i in range(num_chnl_pts):
                if channel_points[i].station == BFE_pnt.station:
                    if i != num_chnl_pts-1 and i != 0:
                        angle1 = self._angle(channel_points[i-1], channel_points[i])
                        angle2 = self._angle(channel_points[i], channel_points[i+1])
                        return (angle1+angle2)/2
                    elif i == 0:
                        # On first vertix
                        return self._angle(channel_points[0], channel_points[1])
                    elif i == num_chnl_pts-1:
                        # On last vertix
                        return self._angle(channel_points[num_chnl_pts-2], channel_points[num_chnl_pts-1])
            # Not found
            raise BFENotFound
    
def import_BFE_from_CSV(csv_filename):
    """ Parses csv file from hec-ras in format:
    
        River,Reach,River Sta,Profile,W.S. Elev,Cum Ch Len
        
        Internal bridge sections can/should be turned on to improve BFE placement
        at bridges. Will also accept the RAS table header. 
        
        Returns RiverSystem object. 
    """
    ### This should be modified to handle a single reach.
    rs = RiverSystem()
    first_lap = True
    river_reach = []
    with open(csv_filename) as infile:
        for line in infile:
            fields = line.strip().split(',')
            # Check for header
            if first_lap:
                first_lap = False
                if fields[0] == 'River' and fields[1] == 'Reach':
                    try:
                        # Skip second line of header
                        next(infile)
                        continue
                    except StopIteration:
                        arcpy.AddError('Error: No linefeed/only one line in file. Did you save as a Mac csv?')
                        raise
            # Ignore culvert/bridge lines
            if fields[3] == '' or fields[4] == '':
                continue
            # Create/get reach and create cross section
            current_reach = rs.get_reach(fields[0], fields[1])
            current_reach.add_XS(fields[2], fields[3], fields[4], fields[5])
    return rs
        
def main():
    # Process parameters
    BFE_file = arcpy.GetParameterAsText(0)
    channel_filename = arcpy.GetParameterAsText(1)
    channel_river_field = arcpy.GetParameterAsText(2)
    channel_reach_field = arcpy.GetParameterAsText(3)
    outfilename = arcpy.GetParameterAsText(4)
    convert_to_CAD = arcpy.GetParameterAsText(5)
    
    # Import RAS data from csv
    arcpy.AddMessage('Importing BFEs from '+BFE_file)
    rs = import_BFE_from_CSV(BFE_file)
    
    # Process RAS data and calculate BFE locations
    arcpy.AddMessage('Calculating BFE locations...')
    rs.sort_all()
    rs.calc_all_reach_lengths()
    rs.calc_all_BFEs()
    arcpy.AddMessage('Done.')

    # Create BFEs in GIS
    create_BFEs = CreateBFEs(rs, channel_filename, channel_river_field, channel_reach_field, outfilename)
    create_BFEs.set_BFE_dimensions(50, True, 25)
    create_BFEs.create_BFEs()

    # Convert BFEs to CAD
    if convert_to_CAD == 'true':
        arcpy.AddMessage('Exporting to CAD')
        arcpy.ExportCAD_conversion(outfilename, 'DWG_R2010', outfilename[:-3]+'dwg')
    
    time.sleep(3)

if __name__ == '__main__':
    main()
