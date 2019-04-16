"""
Uses HEC-RAS output to create floodplain extents as points. Includes interface to 
ArcGIS toolbox.

Mike Bannister
mike.bannister@respec.com
2017
version 0.11
"""

import arcpy
import os, sys
import collections
import math
path = os.path.join(os.path.dirname(__file__), '../parserasgeo')
sys.path.insert(0, path)
import parserasgeo as prg

WS_extent = collections.namedtuple('WS_extent', ['river', 'reach', 'XS_ID', 'profile', 'left_sta', 'right_sta', 'WSEL'])

def import_extents(infilename):
    """
    Import floodplain extents or bank stations from infilename. infilname is CSV in rasupdatesec format and may
    start with the River column, or just the Reach column if using single reach output.
    """
    extents_list=[]
    first_lap = True
    with open(infilename) as infile:
        for line in infile:
            # Ignore header if it exists
            if first_lap == True:
                fields = line.strip().split(',')
                if fields[0].find('River') > -1 or fields[0].find('Reach') > -1:  # Compatibility with '\xef\xbb\xbf' for UTF-8
                    line = next(infile)
                    line = next(infile)
                first_lap = False
            
            # Process remaining lines
            if line != '\n' and line[:6] != ',,,,,,' and line[:5] != ',,,,,':
                fields = line.strip().split(',')
                # Starts with 'River'
                if len(fields) == 7:
                    arcpy.AddMessage(str(fields))
                    xs_id = float(fields[2].split()[0])  # Strip name from xs ID if present
                    new_extent = WS_extent(fields[0], fields[1], xs_id, fields[3], float(fields[4]), 
                                float(fields[5]), float(fields[6]))
                # Starts with 'Reach'
                elif len(fields) == 6:
                    arcpy.AddMessage(str(fields))
                    xs_id = float(fields[1].split()[0])  # Strip name from xs ID if present
                    new_extent = WS_extent('Unknown', fields[0], xs_id, fields[2], float(fields[3]), 
                            float(fields[4]), float(fields[5]))
                else:
                    arcpy.AddError('Error in line:' + line.strip() +
                        '\nInput .csv must be in format: [River], Reach, XS_ID, Profile, Left Sta, Right Sta, ' +
                        'WSEL. Exiting.')
                    sys.exit()
                extents_list.append(new_extent)
    return extents_list


def same_cross_section(XS_1, XS_2, round_stationing, round_digits):
    """ 
    Compare cross section ID's, possibly rounding them
    XS_1, XS_2:     cross section ID's (float)
    round_stationing: boolean, round yes/no?
    round_digits:   Number of digits to round to
    """
    if round_stationing:
        if round(XS_1, round_digits) == round(XS_2, round_digits):
            return True
        else:
            return False
    else:
        if XS_1 == XS_2:
            return True
        else:
            return False
        
   
def create_WS_extents(extents_file, XSfilename, XS_ID_field, round_stationing, round_digits, geo_file, full_outfilename):
    arcpy.SetProgressor("default", "Preparing to create RAS extents...")
    arcpy.AddMessage('Importing extents... ')
    extents_list = import_extents(extents_file)

    outfilename = os.path.basename(full_outfilename)
    outfilepath = os.path.dirname(full_outfilename)
    
    try:
        arcpy.AddMessage('Creating empty output shapefile: '+full_outfilename)
        spatial_reference = arcpy.Describe(XSfilename).spatialReference
        arcpy.CreateFeatureclass_management(outfilepath, outfilename, 'POINT', '', '', '', spatial_reference)
        arcpy.AddField_management(full_outfilename, 'River', 'STRING')
        arcpy.AddField_management(full_outfilename, 'Reach', 'STRING')
        arcpy.AddField_management(full_outfilename, 'XS_ID', 'DOUBLE')
        arcpy.AddField_management(full_outfilename, 'Profile', 'STRING')
        arcpy.AddField_management(full_outfilename, 'Position', 'STRING')
        arcpy.AddField_management(full_outfilename, 'Elevation', 'FLOAT')
        arcpy.AddField_management(full_outfilename, 'Layer', 'STRING')
    except:
        arcpy.AddError('Unable to create '+full_outfilename+'. Is the shape file open in another program or is the ' + 
            'workspace being edited?')
        sys.exit()

    # Correct for skew and offset
    if geo_file != '':
        correct_extents(geo_file, extents_list, round_digits)
        
    arcpy.SetProgressor("step", "Creating extents points..." , 0, 100, 10)
    arcpy.AddMessage('Populating output shapefile... ')

    try:
        total_extents = len(extents_list)
        current_extent = 0
        extents_created = []
        with arcpy.da.SearchCursor(XSfilename, ['SHAPE@', XS_ID_field]) as XS_cursor:
            with arcpy.da.InsertCursor(full_outfilename, ['SHAPE@', 'River', 'Reach', 'XS_ID', 'Profile', 
                'Position', 'Elevation', 'Layer']) as extent_cursor:
                
                # Loop through all XS in shapefile
                for cross_section in XS_cursor:
                    # loop through all extents
                    for row in extents_list:
                        if same_cross_section(row.XS_ID, cross_section[1], round_stationing, round_digits):
                            #Have a match, create extents
                            geo = cross_section[0]
                            left_point = geo.positionAlongLine(row.left_sta, False)
                            right_point = geo.positionAlongLine(row.right_sta, False)
                            extent_cursor.insertRow([left_point, row.river, row.reach, row.XS_ID, row.profile, 
                                'left', row.WSEL, row.profile])
                            extent_cursor.insertRow([right_point, row.river, row.reach, row.XS_ID, row.profile, 
                                'right', row.WSEL, row.profile])

                            #Keep track of created extents and update progress bar
                            extents_created.append(row.XS_ID)
                            if current_extent % (int(total_extents/10)) == 0:
                                arcpy.SetProgressorPosition()
                            current_extent += 1
    except:
        arcpy.AddError('Error creating water surface extents at cross section '+str(row.XS_ID)+'\n')
        raise

    arcpy.AddMessage(str(len(extents_created)) + ' extent pairs (left/right) created out of ' + str(total_extents) + 
                    ' total extent pairs in ' + extents_file)
    if current_extent < total_extents:
        # arcpy.AddWarning('totatl_extents='+str(total_extents)+', current_extent='+str(current_extent))
        missing_XS = []
        for row in extents_list:
            if (not row.XS_ID in extents_created) and (not row.XS_ID in missing_XS):
                missing_XS.append(row.XS_ID)
        missing_string = ', '.join([str(XS) for XS in missing_XS])        
        # TODO - This is a hack, we should never be, but, the count in current_extent gets off when there are
        #       multiple XSs with the same name. This may be fixed by current_extent < total_extents above
        if len(missing_XS) > 0:
            arcpy.AddWarning('Extents were listed in ' + extents_file + ' but not created for the following missing '+
                    str(len(missing_XS))+' cross sections: ' + missing_string)


def correct_extents(geo_file, extents_list, round_digits):
    """ 
    Correct extents for skew and offset
    :param geo_file: - name of RAS geometry file
    :param extents_list: - list of extents from import_extents()
    :param round_digits: - digits to round xs ids to
    """   
    ras_geo = prg.ParseRASGeo(geo_file)
    
    if round_digits != 0 and round_digits != '':
        rnd = True
    else:
        rnd = False

    for i, ex in enumerate(extents_list):
        # Pull info from RAS geometry file
        try:
            if rnd:
                geo_xs = ras_geo.return_xs_by_id(float(ex.XS_ID), rnd=rnd, digits=round_digits)
            else:
                geo_xs = ras_geo.return_xs_by_id(float(ex.XS_ID))
        except prg.CrossSectionNotFound:
            arcpy.AddWarning('Cross section '+ ex.river + '/' + ex.reach + '-' + str(ex.XS_ID) + ' is in cross ' +
                    'section shapefile but is not in RAS geometry file. Skipping')
            continue

        offset = geo_xs.sta_elev.points[0][0]
        skew = geo_xs.skew.angle
        
        # if nothing changes, skip this extent
        if offset == 0 and skew is None:
            continue

        left_sta = ex.left_sta
        right_sta = ex.right_sta

        if offset != 0:
            arcpy.AddWarning('Correcting offset of ' + str(offset) + ' at XS ' + ex.river + '/' + ex.reach + '-' +
                    str(ex.XS_ID))
            left_sta = left_sta - offset
            right_sta = right_sta - offset
        if skew is not None:
            arcpy.AddWarning('Correcting skew of ' + str(skew) + ' at XS ' + ex.river + '/' + ex.reach + '-' +
                    str(ex.XS_ID))
            left_sta = left_sta/math.cos(math.radians(skew))
            right_sta = right_sta/math.cos(math.radians(skew))

        # Create new, corrected extent and replace the old one
        fixed = WS_extent(ex.river, ex.reach, ex.XS_ID, ex.profile, left_sta, right_sta, ex.WSEL)
        extents_list[i] = fixed


def main():
    extents_file = arcpy.GetParameterAsText(0)
    cross_sections = arcpy.GetParameterAsText(1)
    XS_ID_field = arcpy.GetParameterAsText(2)
    round_stationing = arcpy.GetParameterAsText(3)
    round_digits = arcpy.GetParameterAsText(4)
    geo_file = arcpy.GetParameterAsText(5)
    outfilename = arcpy.GetParameterAsText(6)
    convert_to_CAD = arcpy.GetParameterAsText(7)

    arcpy.AddMessage('geofile: "'+ geo_file+ '"')
    if geo_file == '':
        arcpy.AddMessage('No HEC-RAS geometry file was supplied, not correcting skew and offset')


    if round_stationing == 'true':
        round_stationing = True
    else:
        round_stationing = False
        
    if round_digits != '':
        round_digits = int(round_digits)
    elif round_stationing:
            round_digits = 0
            arcpy.AddWarning('Rounding digits left blank, defaulting to 0')

    arcpy.AddMessage('Creating: '+ outfilename)
    create_WS_extents(extents_file, cross_sections, XS_ID_field, round_stationing, round_digits, geo_file, outfilename)
        
    # Convert points to CAD
    if convert_to_CAD == 'true':
        arcpy.AddMessage('Exporting to CAD')
        arcpy.ExportCAD_conversion(outfilename, 'DWG_R2010', outfilename[:-3]+'dwg')

if __name__ == '__main__':
    main()
