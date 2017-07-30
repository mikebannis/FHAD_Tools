"""
Creates perpendicular lines along an alignment to visually test HEC-RAS cross section reach
lengths. Includes interface to ArcGIS toolbox

Mike Bannister
mike.bannister@respec.com
2017
"""
import bfetool
import os

bfetool.BFE_ELEV_FIELD = 'XS_ID'

class CrossSectionTest(bfetool.CreateBFEs):
    def create_test_XS(self):
        XS_points = self._create_test_XS_points()
        self._create_test_XS_lines(XS_points)
        self._delete_temp_file(XS_points)

    def _create_test_XS_points(self):
        """ Creates temporary shapefile of XS points. This is step 1 
            Returns temporary shapefile name with full path
        """
        arcpy.SetProgressor("default", "Preparing to create test cross sections...")

        # Set up test XS point shape file
        temp_point_file = self._temp_filename()+'.shp'
        self._setup_shapefile(temp_point_file, 'POINT', 'Creating temporary XS point shapefile: ')
            
        arcpy.SetProgressor("step", "Creating temporary XS points..." , 0, 100, 10)
        arcpy.AddMessage('Populating temporary XS points... ')
        try:
            total_XS = self.rs.number_of_XSs()
            num_XSs_created = 0
            with arcpy.da.SearchCursor(self.channel_filename, ['SHAPE@', self.channel_river_field, 
                self.channel_reach_field]) as channel_cursor:
                with arcpy.da.InsertCursor(temp_point_file, ['SHAPE@', self.channel_river_field,
                    self.channel_reach_field, bfetool.BFE_ELEV_FIELD, bfetool.BFE_STA_FIELD]) as XS_cursor:
                    for channel in channel_cursor:
                        # See if we have XSs for that reach
                        if self.rs.reach_exists(channel[1], channel[2]):
                            current_reach = self.rs.get_reach(channel[1], channel[2])
                        else:
                            continue
                        # Got XSs, lets make some points!
                        channel_geo = channel[0]
                        for current_XS in current_reach.cross_sections:
                            new_point = channel_geo.positionAlongLine(current_XS.cum_length, False)
                            XS_cursor.insertRow([new_point, channel[1], channel[2], current_XS.ID, current_XS.cum_length])

                            #Keep track of created XSs and update progress bar
                            num_XSs_created += 1
                            if num_XSs_created % (int(total_XS/10)) == 0:
                                arcpy.SetProgressorPosition()
        except Exception as detail:
            arcpy.AddError('Error creating temporary XS points: ' + str(detail))
            raise

        arcpy.AddMessage(str(num_XSs_created)+' XSs created out of '+str(total_XS)+' total XSs.')
        if num_XSs_created > total_XS:
            arcpy.AddWarning('Warning! More XSs were created than exist in the input file! Are there duplicate alignments?')
        if num_XSs_created < total_XS:
            arcpy.AddWarning('Warning! Not all XSs in input file were created!')
        return (temp_point_file)
    
    def _create_test_XS_lines(self, XS_points):
        self._create_BFE_lines(XS_points)
        
    def _setup_shapefile(self, filename, shape, message):
        """ Creates output/temp shapefile, adds fields, and updates the arcpy status dialog  
            This had to be modified to make BFE_ELEV_FIELD text
        """
        try:
            arcpy.AddMessage(message+filename)
            spatial_reference = arcpy.Describe(self.channel_filename).spatialReference
            arcpy.CreateFeatureclass_management(os.path.dirname(filename), os.path.basename(filename), 
                                                    shape, '', '', '', spatial_reference)
            arcpy.AddMessage('Adding fields...')
            arcpy.AddField_management(filename, self.channel_river_field, 'TEXT', field_length = bfetool.FIELD_LENGTH)
            arcpy.AddField_management(filename, self.channel_reach_field, 'TEXT', field_length = bfetool.FIELD_LENGTH)
            arcpy.AddField_management(filename, bfetool.BFE_ELEV_FIELD, 'TEXT', field_length=bfetool.FIELD_LENGTH)
            arcpy.AddField_management(filename, bfetool.BFE_STA_FIELD, 'DOUBLE')       
        except:
            arcpy.AddError('Unable to create '+filename+'. Is the shape file open in another program or is the workspace being edited?')
            raise
        else:
            arcpy.AddMessage('Done.')
            
        
def main():
     # Process parameters
    XS_file = arcpy.GetParameterAsText(0)
    channel_filename = arcpy.GetParameterAsText(1)
    channel_river_field = arcpy.GetParameterAsText(2)
    channel_reach_field = arcpy.GetParameterAsText(3)
    xs_test_length = float(arcpy.GetParameterAsText(4))
    outfilename = arcpy.GetParameterAsText(5)
    convert_to_CAD = arcpy.GetParameterAsText(6)
    
    # Import RAS data from csv
    arcpy.AddMessage('Importing cross sections from '+XS_file)
    rs = bfetool.import_BFE_from_CSV(XS_file)
    
    # Process RAS data and c
    rs.sort_all()
    arcpy.AddMessage('Done.')

    # Create BFEs in GIS
    create_XSs = CrossSectionTest(rs, channel_filename, channel_river_field, channel_reach_field, outfilename,
            BFE_length=xs_test_length)
    create_XSs.create_test_XS()

    # Convert BFEs to CAD
    if convert_to_CAD == 'true':
        arcpy.AddMessage('Exporting to CAD')
        arcpy.ExportCAD_conversion(outfilename, 'DWG_R2010', outfilename[:-3]+'dwg')
    
    time.sleep(3)
    
if __name__ == '__main__':
    main()
