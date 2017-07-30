"""
Creates lines representing HEC-RAS n-values RAS geometry file

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
N_VALUE_FIELD = 'Mannings_n'
FIELD_LENGTH = 50
DEBUG = False


class CrossSectionLengthError(Exception):
    pass


class ManningPoint(object):
    """
    Used for sorting cross section vertices and n-value changes.
    """
    def __init__(self, x, y, station, n_value=-1):
        self.X = x
        self.Y = y
        self.station = station
        self.n_value = n_value

    def __str__(self):
        return str(self.X)+', '+str(self.Y)+', sta='+str(self.station)+', n_value='+str(self.n_value)

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
        arcpy.AddField_management(filename, N_VALUE_FIELD, 'FLOAT', '')
    except Exception as e:
        error(str(e))
        error('Unable to create ' + filename +
              '. Is the shape file open in another program or is the workspace being edited?')
        sys.exit()
    else:
        arcpy.AddMessage('Done.')


def _create_n_value_lines(line_geo, orig_n_values, xs_id):
    """
    Creates arcpy polylines representing portions of a cross section with a consistent manning's n
    :param line_geo: cross section polyline geometry from arcpy.da.SearchCursor
    :param n_values: list of tuples from rasgeotools CrossSection.mannings_n
    :param xs_id: id of the current cross section, only used for reporting
    :return: a list of tuples [(arcpy polyline, n-value (float), ... ]
    """
    n_values = list(orig_n_values)

    # Correct offset if first station is not 0
    if n_values[0][0] != 0:
        offset = n_values[0][0]
        n_values = [(sta-offset, b, c) for sta, b, c in n_values]

    # verify n-values aren't longer than cross section
    if n_values[-1][0] >= line_geo.length:
        # Check if it's the last station on the cross section
        if abs(n_values[-1][0] - line_geo.length) < 1:
            n_values.pop(-1)
            warn('Cross section ' + str(xs_id) + ' appears to have n-value change at last station. Ignoring.')
        else:
            raise CrossSectionLengthError

    # Extract station 0 n-value - this is done to avoid possible rounding errors with positionAlongLine
    xs_points = _array_to_list(line_geo.getPart(0))
    first_n_value = n_values.pop(0)
    first_point = xs_points[0]
    combo_points = [ManningPoint(first_point.X, first_point.Y, 0, first_n_value[1])]

    # Extract rest of the n-values
    for station, n_value, _ in n_values:
        new_point = line_geo.positionAlongLine(station).firstPoint
        new_point = ManningPoint(new_point.X, new_point.Y, station, n_value)
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
        new_point = ManningPoint(xs_point.X, xs_point.Y, station)
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
    assert points[0].n_value != -1

    # Split points into n-value segments
    current_n_value = points[0].n_value
    current_index = 0
    segments = []
    for i in range(1, len(points)):
        if points[i].n_value != -1:
            new_segment = (points[current_index:i+1], current_n_value)
            segments.append(new_segment)
            current_index = i
            current_n_value = points[i].n_value
    new_segment = (points[current_index:i+1], current_n_value)
    segments.append(new_segment)

    # convert segments to arcpy polylines
    n_lines = []
    for points, n_value in segments:
        arc_array = arcpy.Array()
        arc_point = arcpy.Point()
        for point in points:
            arc_point.X = point.X
            arc_point.Y = point.Y
            arc_array.add(arc_point)
        n_lines.append((arcpy.Polyline(arc_array), n_value))
    return n_lines


def _dist(point1, point2):
    """
    Returns distance between point1 and point 2
    """
    return ((point1.X - point2.X)**2 + (point1.Y - point2.Y)**2)**0.5


def n_value_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile):
    """
    Combines HEC-RAS geometry file and cross section shapefile to create polylines representing areas of consistent
    surface roughness.

    :param geofile: HEC-RAS geoemtry file
    :param xs_shape_file: shape file of cross sections
    :param xs_id_field: cross section id field in xs_shape_file
    :param river_field:
    :param reach_field:
    :param outfile: name of output shape file
    :return: nothing
    """
    # Setup output shapefile
    spatial_reference = arcpy.Describe(xs_shape_file).spatialReference
    _setup_output_shapefile(outfile, xs_id_field, river_field, reach_field, spatial_reference)
    message('Importing HEC-RAS geometry...')
    ras_geo = prg.ParseRASGeo(geofile)
    message('Done.\nCreating surface roughness review lines...')

    num_xs_ras_geo = ras_geo.number_xs()
    num_xs_gis = 0
    num_xs_processed = 0
    with arcpy.da.SearchCursor(xs_shape_file, ['SHAPE@', xs_id_field, river_field, reach_field]) as xs_cursor:
        with arcpy.da.InsertCursor(outfile, ['SHAPE@', xs_id_field, river_field, reach_field,
                                             N_VALUE_FIELD]) as out_cursor:
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

                # Get RAS cross section
                try:
                    geo_xs = ras_geo.return_xs(xs_id, river, reach, strip=True)
                except prg.CrossSectionNotFound:
                    warn('Warning: Cross section ' + str(xs_id) + ' is in cross section shape file but is not in ' + \
                         'the HEC-RAS geometry file. Continuing')
                    continue

                # Check for duplicate n-values
                test = geo_xs.mannings_n.check_for_duplicate_n_values()
                if test is not None:
                    message('Cross section ' + str(xs_id) + ' has duplicate n-values at the following stations: ' + \
                         str(test) + '. This is not visible in the cross section editor but can be seen in the ' + \
                         'geometry file.')

                test = geo_xs.mannings_n.check_for_redundant_n_values()
                if test is not None:
                    message('Cross section ' + str(xs_id) + ' has redundant n-values at the following stations: ' + \
                         str(test))

                # Fix cross section skew (if present)
                n_values = _correct_skew(geo_xs)

                # Enough guard clauses, let's make the n-value review line
                try:
                    n_lines = _create_n_value_lines(geo, n_values, xs_id)
                except CrossSectionLengthError:
                    warn('Error: N-value stationing for cross section ' + str(xs_id) + ' in RAS geometry exceeds ' + \
                         'GIS feature length. Ignored.')
                    continue

                num_xs_processed += 1
                for n_line in n_lines:
                    out_cursor.insertRow([n_line[0], xs_id, river, reach, n_line[1]])

    warn('There are ' + str(num_xs_ras_geo) + ' cross sections in the HEC-RAS geometry and ' + str(num_xs_gis) + \
         ' cross sections in the cross section shape file. ' + str(num_xs_processed) + ' cross sections were' + \
         ' successfully converted into surface roughness review lines.')


def _correct_skew(geo_xs):
    """
    Corrects Mannings n values for skew, if present
    :param geo_xs: prg.CrossSection object
    :return: list of n-values in prg format
    """
    n_values = geo_xs.mannings_n.values
    if geo_xs.skew.angle:
        skewed_values = [(sta/math.cos(math.radians(geo_xs.skew.angle)), b, c) for sta, b, c in n_values]
        return skewed_values
    else:
        return n_values


def main():
    geofile = arcpy.GetParameterAsText(0)
    xs_shape_file = arcpy.GetParameterAsText(1)
    xs_id_field = arcpy.GetParameterAsText(2)
    river_field = arcpy.GetParameterAsText(3)
    reach_field = arcpy.GetParameterAsText(4)
    outfile = arcpy.GetParameterAsText(5)

    n_value_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile)
    import time
    time.sleep(3)


if __name__ == '__main__':
    main()
