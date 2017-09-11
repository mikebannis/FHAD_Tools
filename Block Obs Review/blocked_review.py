"""
Creates lines representing HEC-RAS obstructions from RAS geometry file

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

BLOCKED_FIELD = 'Blocked_El'
BLOCKED_STATUS = 'Blocked'
FIELD_LENGTH = 50
DEBUG = False


class CrossSectionLengthError(Exception):
    pass


class BlockedPoint(object):
    """
    Used for sorting cross section vertices and n-value changes.
    """
    def __init__(self, x, y, station, blocked=-1):
        self.X = x
        self.Y = y
        self.station = station
        self.blocked = blocked

    def __str__(self):
        return str(self.X)+', '+str(self.Y)+', sta='+str(self.station)+', blocked='+str(self.blocked)

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
        arcpy.AddField_management(filename, BLOCKED_FIELD, 'FLOAT', '')
        arcpy.AddField_management(filename, BLOCKED_STATUS, 'TEXT', field_length=FIELD_LENGTH)

    except Exception as e:
        error(str(e))
        error('Unable to create ' + filename +
              '. Is the shape file open in another program or is the workspace being edited?')
        sys.exit()
    else:
        arcpy.AddMessage('Done.')


def _create_blocked_lines(line_geo, geo_xs):
    """
    Creates arcpy polylines representing portions of a cross section with a consistent manning's n
    :param line_geo: cross section polyline geometry from arcpy.da.SearchCursor
    :param geo_xs CrossSection object from parserasgeo
    :return: a list of tuples [(arcpy polyline, n-value (float), ... ]
    """
    def skew(n):
        # Handle no skew (None)
        if geo_xs.skew.angle:
            skew_value = geo_xs.skew.angle
        else:
            skew_value = 0
        return n/math.cos(math.radians(skew_value))

    # convert blocked values to list more friendly to the legacy (n-value) code
    # Assume first blocked obstruction doesn't start at 0
    # TODO - make this handle the assumption being wrong
    orig_blocked = geo_xs.obstruct.blocked
    arcpy.AddMessage(str(geo_xs.header.xs_id) + str(orig_blocked))

    blocked_values = []
    if geo_xs.obstruct.blocked_type == -1:  # blocked obstruction
        # Assume first blocked obstruction doesn't start at 0
        # TODO - make this handle the assumption being wrong
        blocked_values.append((0, 0, 999))

        for value in orig_blocked:
            # Look out for blank blocked lines
            if value[0] == '' or value[1] == '':
                continue
            # Look out for blank elevations
            if value[2] == '':
                elev = 99999
            else:
                elev = value[2]

            blocked_values.append((value[0], elev, 999))
            blocked_values.append((value[1], 0, 999))
    else:  # normal obstruction
        blocked_values.append((0, 0, 999))
        left_blocked = orig_blocked[0]
        right_blocked = orig_blocked[1]
        # See if left blocked is valid
        if left_blocked[1] != '':
            if left_blocked[2] == '':
                elev = 99999
            else:
                elev = left_blocked[2]
            blocked_values.append((0, elev, 999))
            blocked_values.append((left_blocked[1], 0, 999))
        # See if right blocked is valid
        if right_blocked[0] != '':
            if right_blocked[2] == '':
                elev = 99999
            else:
                elev = right_blocked[2]
            blocked_values.append((right_blocked[0], elev, 999))
            blocked_values.append((geo_xs.sta_elev.points[-1][0], 0, 999))

    # verify n-values aren't longer than cross section
    if blocked_values[-1][1] > line_geo.length:
            raise CrossSectionLengthError

    # Fix skew
    blocked_values = [(skew(sta), b, c) for sta, b, c in blocked_values]

    # Correct cross section station offset issues
    offset = geo_xs.sta_elev.points[0][0]
    if offset != 0:
        blocked_values = [(sta - offset, b, c) for sta, b, c in blocked_values]

    # Extract station 0 n-value - this is done to avoid possible rounding errors with positionAlongLine
    xs_points = _array_to_list(line_geo.getPart(0))
    first_n_value = blocked_values.pop(0)
    first_point = xs_points[0]
    combo_points = [BlockedPoint(first_point.X, first_point.Y, 0, first_n_value[1])]

    # Extract rest of the n-values
    for station, n_value, _ in blocked_values:
        new_point = line_geo.positionAlongLine(station).firstPoint
        new_point = BlockedPoint(new_point.X, new_point.Y, station, n_value)
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
        new_point = BlockedPoint(xs_point.X, xs_point.Y, station)
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
    assert points[0].blocked != -1

    # Split points into n-value segments
    current_blocked = points[0].blocked
    current_index = 0
    segments = []
    for i in range(1, len(points)):
        if points[i].blocked != -1:
            new_segment = (points[current_index:i+1], current_blocked)
            segments.append(new_segment)
            current_index = i
            current_blocked = points[i].blocked
    new_segment = (points[current_index:i+1], current_blocked)
    segments.append(new_segment)

    # convert segments to arcpy polylines
    n_lines = []
    for points, blocked in segments:
        arc_array = arcpy.Array()
        arc_point = arcpy.Point()
        for point in points:
            arc_point.X = point.X
            arc_point.Y = point.Y
            arc_array.add(arc_point)
        n_lines.append((arcpy.Polyline(arc_array), blocked))
    return n_lines


def _dist(point1, point2):
    """
    Returns distance between point1 and point 2
    """
    return ((point1.X - point2.X)**2 + (point1.Y - point2.Y)**2)**0.5


def obstruction_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile):
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
    message('Done.\nCreating blocked obstruction review lines...')

    num_xs_ras_geo = ras_geo.number_xs()
    num_xs_gis = 0
    num_xs_processed = 0
    with arcpy.da.SearchCursor(xs_shape_file, ['SHAPE@', xs_id_field, river_field, reach_field]) as xs_cursor:
        with arcpy.da.InsertCursor(outfile, ['SHAPE@', xs_id_field, river_field, reach_field,
                                             BLOCKED_FIELD, BLOCKED_STATUS]) as out_cursor:
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
                    geo_xs = ras_geo.return_xs(xs_id, river, reach, strip=True)
                    # ras_geo = prg_old.return_xs(geo_list, xs_id, river, reach)
                except prg.CrossSectionNotFound:
                    warn('Warning: Cross section ' + str(xs_id) + '/' + str(river) + '/' + str(reach) + \
                         ' is in cross section shape file but is not in the HEC-RAS geometry file. Continuing')
                    continue

                # Verify presence of obstructions
                if geo_xs.obstruct.num_blocked is None:
                    continue

                # Enough guard clauses, let's make the n-value review line
                try:
                    blocked_lines = _create_blocked_lines(geo, geo_xs)
                except CrossSectionLengthError:
                    warn('Error: N-value stationing for cross section ' + str(xs_id) + ' in RAS geometry exceeds ' + \
                         'GIS feature length. Ignored.')
                    continue

                num_xs_processed += 1
                for blocked_line in blocked_lines:
                    if blocked_line[1] == 0:
                        status = 'no'
                    else:
                        status = 'yes'
                    out_cursor.insertRow([blocked_line[0], xs_id, river, reach, blocked_line[1], status])

    warn('There are ' + str(num_xs_ras_geo) + ' cross sections in the HEC-RAS geometry and ' + str(num_xs_gis) +
         ' cross sections in the cross section shape file. Obstructions were created at ' + str(num_xs_processed) +
         ' cross sections.')


def main():
    geofile = arcpy.GetParameterAsText(0)
    xs_shape_file = arcpy.GetParameterAsText(1)
    xs_id_field = arcpy.GetParameterAsText(2)
    river_field = arcpy.GetParameterAsText(3)
    reach_field = arcpy.GetParameterAsText(4)
    outfile = arcpy.GetParameterAsText(5)

    obstruction_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile)

if __name__ == '__main__':
    main()
