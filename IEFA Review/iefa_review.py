"""
Creates lines representing HEC-RAS ineffective flow areas from RAS geometry file

Mike Bannister
mike.bannister@respec.com
2017
"""
import math
import arcpy
import os
import sys
path = os.path.join(os.path.dirname(__file__), '../../parserasgeo')
sys.path.insert(0, path)
import parserasgeo as prg

IEFA_FIELD = 'IEFA_El'
IEFA_STATUS = 'IEFA'
FIELD_LENGTH = 50
DEBUG = False


class CrossSectionLengthError(Exception):
    pass


class IefaPoint(object):
    """
    Used for sorting cross section vertices and n-value changes.
    """
    def __init__(self, x, y, station, iefa=-1):
        self.X = x
        self.Y = y
        self.station = station
        self.iefa = iefa

    def __str__(self):
        return str(self.X)+', '+str(self.Y)+', sta='+str(self.station)+', iefa='+str(self.iefa)

    def __repr__(self):
        return self.__str__()


# The following 3 functions simplify development
def message(x):
    arcpy.AddMessage(x)


def warn(x):
    arcpy.AddWarning(x)


def error(x):
    arcpy.AddError(x)


def _array_to_list(arc_array):
    """
    Converts arcpy array to a list of arcpy points
    :param arc_array: result of converting multipart feature into line (geo.getPart(0))
    :return: list of arcpy points
    """
    points = []
    for i in range(arc_array.count):
        points.append(arc_array.getObject(i))
    return points


def _setup_output_shapefile(filename, xs_id_field, river_field, reach_field, spatial_reference):
    try:
        message('Creating output shapefile: ' + filename)
        arcpy.CreateFeatureclass_management(os.path.dirname(filename), os.path.basename(filename),
                                            'POLYLINE', '', '', '', spatial_reference)
        message('Adding fields...')
        arcpy.AddField_management(filename, xs_id_field, 'FLOAT', '')
        arcpy.AddField_management(filename, river_field, 'TEXT', field_length=FIELD_LENGTH)
        arcpy.AddField_management(filename, reach_field, 'TEXT', field_length=FIELD_LENGTH)
        arcpy.AddField_management(filename, IEFA_FIELD, 'FLOAT', '')
        arcpy.AddField_management(filename, IEFA_STATUS, 'TEXT', field_length=FIELD_LENGTH)

    except Exception as e:
        error(str(e))
        error('Unable to create ' + filename +
              '. Is the shape file open in another program or is the workspace being edited?')
        sys.exit()
    else:
        arcpy.AddMessage('Done.')


def _create_iefa_lines(line_geo, geo_xs):
    """
    Creates arcpy polylines representing portions of a cross section with a consistent manning's n
    This handles skew, but doesn't currently handle offset cross sections
    :param line_geo: cross section polyline geometry from arcpy.da.SearchCursor
    :param iefa: skew corrected iefa
    :param geo_xs: CrossSection object from parserasgeo
    :return: a list of tuples [(arcpy polyline, n-value (float)), ... ]
    """
    # TODO - skew is currnently being handled in multiple places. This should be consolidated for readability.
    # TODO (cont) - see Block Obs Review for an example
    def skew(n):
        # Handle no skew (None)
        if geo_xs.skew.angle:
            skew_value = geo_xs.skew.angle
        else:
            skew_value = 0
        return n/math.cos(math.radians(skew_value))

    orig_iefa = geo_xs.iefa.iefa_list
    # convert iefa values to list more friendly to the legacy (n-value) code

    iefa_values = []
    if geo_xs.iefa.type == -1:  # blocked iefa
        # Assume first iefa obstruction doesn't start at 0
        # TODO - make this handle the assumption being wrong
        iefa_values.append((0, 0, 999))

        for value in orig_iefa:
            # Look out for blank iefa lines
            if value[0] == '' or value[1] == '':
                continue
            # Look out for blank elevations
            if value[2] == '':
                elev = 99999
            else:
                elev = value[2]

            iefa_values.append((skew(value[0]), elev, 999))
            iefa_values.append((skew(value[1]), 0, 999))
    else:  # normal iefa
        iefa_values.append((0, 0, 999))
        left_iefa = orig_iefa[0]
        right_iefa = orig_iefa[1]
        # See if left IEFA is valid
        if left_iefa[1] != '':
            if left_iefa[2] == '':
                elev = 99999
            else:
                elev = left_iefa[2]
            iefa_values.append((0, elev, 999))
            iefa_values.append((skew(left_iefa[1]), 0, 999))
        # See if right IEFA is valid
        if right_iefa[0] != '':
            if right_iefa[2] == '':
                elev = 99999
            else:
                elev = right_iefa[2]
            iefa_values.append((skew(right_iefa[0]), elev, 999))
            iefa_values.append((skew(geo_xs.sta_elev.points[-1][0]), 0, 999))

    # verify n-values aren't longer than cross section
    if iefa_values[-1][1] > skew(line_geo.length):
        raise CrossSectionLengthError

    # Correct cross section station offset issues
    offset = geo_xs.sta_elev.points[0][0]
    if offset != 0:
        iefa_values = [(sta-offset, b, c) for sta, b, c in iefa_values]

    # Extract station 0 n-value - this is done to avoid possible rounding errors with positionAlongLine
    xs_points = _array_to_list(line_geo.getPart(0))
    first_n_value = iefa_values.pop(0)
    first_point = xs_points[0]
    combo_points = [IefaPoint(first_point.X, first_point.Y, 0, first_n_value[1])]

    #message('XS -----' + str(geo_xs.header.xs_id))
    #message(str(iefa_values))

    # Extract rest of the n-values
    for station, n_value, _ in iefa_values:
        # Look out for IEFA changes that exceed length of the cut line
        if station > line_geo.length:
            if station - line_geo.length > 0.1:  # small errors are caused by rounding
                warn('At XS {}, IEFA station {},'.format(geo_xs.header.xs_id, station) + \
                     ' exceeds length of GIS cutline ({})'.format(line_geo.length) + \
                     '. Changing station to match end of line.')
            station = line_geo.length
        # positionAlongLine doesn't like negative stations
        if station < 0:
            warn('At XS {}, IEFA station {},'.format(geo_xs.header.xs_id, station) + \
                 ' is being reset to zero.')
            station = 0

        new_point = line_geo.positionAlongLine(station).firstPoint
        new_point = IefaPoint(new_point.X, new_point.Y, station, n_value)
        combo_points.append(new_point)

    # Add stationing and n-value flag to xs_points
    new_xs_points = []
    first_lap = True
    station = 0
    for xs_point in xs_points:
        if first_lap:
            last_point = xs_point
            first_lap = False
        else:
            station += _dist(xs_point, last_point)
        new_point = IefaPoint(xs_point.X, xs_point.Y, station)
        last_point = xs_point
        new_xs_points.append(new_point)
    # Ditch first point, already created above from n-values
    new_xs_points.pop(0)
    combo_points = combo_points + new_xs_points
    combo_points.sort(key=lambda x: x.station)

    return _combo_points_to_polylines(combo_points)


def _combo_points_to_polylines(points):
    """
    Converts list points (must be sorted by station) into arcpy polylines that represent areas of consistent surface
    roughness. Called from _create_n_value_lines()
    :param points: list of ManningPoint objects (sorted)
    :return: list of tuples: (arcpy polyline, n-value (float))
    """
    assert points[0].iefa != -1

    # Split points into n-value segments
    current_iefa = points[0].iefa
    current_index = 0
    segments = []
    for i in range(1, len(points)):
        if points[i].iefa != -1:
            new_segment = (points[current_index:i+1], current_iefa)
            segments.append(new_segment)
            current_index = i
            current_iefa = points[i].iefa
    new_segment = (points[current_index:i+1], current_iefa)
    segments.append(new_segment)

    # convert segments to arcpy polylines
    n_lines = []
    for points, iefa in segments:
        arc_array = arcpy.Array()
        arc_point = arcpy.Point()
        for point in points:
            arc_point.X = point.X
            arc_point.Y = point.Y
            arc_array.add(arc_point)
        n_lines.append((arcpy.Polyline(arc_array), iefa))
    return n_lines


def _dist(point1, point2):
    """
    Returns distance between point1 and point 2
    """
    return ((point1.X - point2.X)**2 + (point1.Y - point2.Y)**2)**0.5


def iefa_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile, rnd=False, digits=0):
    """
    Combines HEC-RAS geometry file and cross section shapefile to create polylines representing areas of consistent
    surface roughness.

    :param geofile: HEC-RAS geoemtry file
    :param xs_shape_file: shape file of cross sections
    :param xs_id_field: cross section id field in xs_shape_file
    :param river_field:
    :param reach_field:
    :param outfile: name of output shape file
    :param rnd: boolean - round XS ids?
    :param digits: number of digits to round to
    """
    # Setup output shapefile
    spatial_reference = arcpy.Describe(xs_shape_file).spatialReference
    _setup_output_shapefile(outfile, xs_id_field, river_field, reach_field, spatial_reference)
    message('Importing HEC-RAS geometry...')
    ras_geo = prg.ParseRASGeo(geofile)
    message('Done.\nCreating IEFA review lines...')

    num_xs_ras_geo = ras_geo.number_xs()
    num_xs_gis = 0
    num_xs_processed = 0
    with arcpy.da.SearchCursor(xs_shape_file, ['SHAPE@', xs_id_field, river_field, reach_field]) as xs_cursor:
        with arcpy.da.InsertCursor(outfile, ['SHAPE@', xs_id_field, river_field, reach_field,
                                             IEFA_FIELD, IEFA_STATUS]) as out_cursor:
            for xs in xs_cursor:
                num_xs_gis += 1
                geo = xs[0]
                xs_id = xs[1]
                river = xs[2]
                reach = xs[3]

                if DEBUG:
                    message('*'*20+'working on xs '+str(xs_id)+'/'+river+'/'+reach)

                if geo.isMultipart:
                    warn('Warning: Cross section ' + xs_id + ' is multipart. Using part 0.')

                try:
                    if type(xs_id) is str or type(xs_id) is unicode:
                        warn('Cross section station for ' + str(xs_id) + ' is a string in GIS data, trying to cast to a number')
                        try:
                            xs_id = float(xs_id)
                        except ValueError:
                            error('Unable to convert XS station ' + str(xs_id) + ' to a number. Please remove any characters from the station ')
                            sys.exit()
                    geo_xs = ras_geo.return_xs(xs_id, river, reach, strip=True, rnd=rnd, digits=digits)
                except prg.CrossSectionNotFound:
                    warn('Warning: Cross section ' + str(xs_id) + '/' + str(river) + '/' + str(reach) + \
                         ' is in cross section shape file but is not in the HEC-RAS geometry file. Continuing')
                    continue

                # Verify presence of IEFA
                if geo_xs.iefa.num_iefa is None:
                    continue

                # Enough guard clauses, let's make the n-value review line
                try:
                    iefa_lines = _create_iefa_lines(geo, geo_xs)
                except CrossSectionLengthError:
                    warn('Error: N-value stationing for cross section ' + str(xs_id) + ' in RAS geometry exceeds ' + \
                         'GIS feature length. Ignored.')
                    continue

                num_xs_processed += 1
                for iefa_line in iefa_lines:
                    if iefa_line[1] == 0:
                        status = 'no'
                    else:
                        status = 'yes'
                    out_cursor.insertRow([iefa_line[0], xs_id, river, reach, iefa_line[1], status])

    warn('There are ' + str(num_xs_ras_geo) + ' cross sections in the HEC-RAS geometry and ' + str(num_xs_gis) + \
         ' cross sections in the cross section shape file. ' + str(num_xs_processed) + ' cross sections were' + \
         ' successfully converted into IEFA review lines.')


def main():
    geofile = arcpy.GetParameterAsText(0)
    xs_shape_file = arcpy.GetParameterAsText(1)
    xs_id_field = arcpy.GetParameterAsText(2)
    river_field = arcpy.GetParameterAsText(3)
    reach_field = arcpy.GetParameterAsText(4)
    outfile = arcpy.GetParameterAsText(5)
    rnd = arcpy.GetParameterAsText(6)
    digits = arcpy.GetParameterAsText(7)

    iefa_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile, rnd)

if __name__ == '__main__':
    main()
