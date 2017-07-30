"""
Measures floodplain (polygon) top width at a cross section (polyline) using arcpy. This 
creates a new shapefile/feature class of polylines that represent the top width of the 
floodplain. An attribute field (ERR_FIELD) is created and indicates if the the measurement
was successfull or not. 

Requires ArcGIS version >= 10.2.1

tw_script.py contains the arcpy toolbox interface for this file.

Mike Bannister
mike.bannister@respec.com
2017
"""
print 'importing arcpy... ',
import arcpy

print 'done'
import sys
import os

ALL_INTERSECTS = 'in_memory\\intersect_pts'
XS_FLAG = 'Cross Section'
INTERSECT_FLAG = 'Intersect'
ERR_FIELD = 'Error'
FIELD_LENGTH = 10


# The below functions can be overridden for use with Arcpy etc.
def message(text):
    print text


def warn(text):
    print text


def error(text):
    print text


def measure(floodplain_file, xs_file, xs_id_field, out_file):
    """
    measures floodplain at cross sections, creates lines representing top width in
    out_file per DFHAD guidelines

    :param floodplain_file:
    :param xs_file:
    :param xs_id_field:
    :param out_file:
    :return:
    """
    # Clear memory
    arcpy.Delete_management('in_memory')

    # Extract floodplain and cross section data
    fp_geo = _get_fp_geo(floodplain_file)
    cross_sections = _get_xs_geo(xs_file, xs_id_field)

    # Intersect floodplain and cross sections, apply to cross section
    message('Intersecting floodplain and cross sections... ')
    all_intersect_pts = ALL_INTERSECTS
    arcpy.Intersect_analysis([floodplain_file, xs_file], all_intersect_pts, 'ALL', '', 'POINT')
    _assign_intersect_to_xs(cross_sections, xs_id_field, all_intersect_pts)
    message('Done.')

    # Create the top width lines
    message('Calculating top widths...')
    for xs in cross_sections:
        #print 'Calcing', xs.xs_id
        # Combine cross section points with points from intersection of cross section and floodplain
        if xs.intersect_pts is not None:
            xs.merge_points()
        else:
            warn('Issue calculating top width at cross section ' + str(xs.xs_id))
            xs.error_flag = True
            continue

        # Try to get a top width
        xs.extract_tw(fp_geo)
        if xs.tw_points is None:
            warn('No top width found at cross section: ' + str(xs.xs_id))
            xs.error_flag = True

    # Export top widths
    spatial_reference = arcpy.Describe(xs_file).spatialReference
    _setup_output_shapefile(out_file, xs_id_field, spatial_reference)
    _export_tw_points_to_shapefile(cross_sections, xs_id_field, out_file)


def _assign_intersect_to_xs(cross_sections, xs_id_field, all_intersect_pts):
    """

    :param cross_sections:
    :param all_intersect_pts:
    :return:
    """
    with arcpy.da.SearchCursor(all_intersect_pts, ['SHAPE@', xs_id_field]) as cursor:
        for row in cursor:
            for xs in cross_sections:
                if xs.xs_id == row[1]:
                    if xs.intersect_pts is None:
                        xs.intersect_pts = _multipoint_to_list(row[0])
                        break
                    else:
                        warn('There appear to be multiple intersections for cross section ' + str(xs.xs_id))
                        xs.error_flag = True


def _export_tw_points_to_shapefile(cross_sections, xs_id_field, out_file):
    """

    :param cross_sections:
    :param out_file:
    :return:
    """
    with arcpy.da.InsertCursor(out_file, ['SHAPE@', xs_id_field, ERR_FIELD]) as cursor:
        for xs in cross_sections:
            if xs.tw_points is not None:
                line = _list_to_arcpy_polyline(xs.tw_points)
                if not xs.error_flag:
                    code = 'OK'
                else:
                    code = 'Error'
            else:
                line = _list_to_arcpy_polyline(xs.points)
                code = 'Error'
            cursor.insertRow([line, xs.xs_id, code])


def _list_to_arcpy_polyline(points):
    array = arcpy.Array()
    for point in points:
        array.append(point)
    return arcpy.Polyline(array)


def _tw_points_to_list(points):
    """
    Returns list of geos in points
    :param points: list of TWPoint objects
    :return: list
    """
    point_list = []
    for point in points:
        point_list.append(point.geo)
    return point_list


def _distance(point1, point2):
    deltax = point2.X - point1.X
    deltay = point2.Y - point1.Y
    return (deltax ** 2 + deltay ** 2) ** 0.5


def _array_to_list(arc_array):
    # Converts arcpy array to a list of arcpy points
    points = []
    for i in range(arc_array.count):
        points.append(arc_array.getObject(i))
    return points


def _multipoint_to_list(arc_points):
    # converts arcpy multipoint object to a list of arcpy points
    points = []
    for i in range(arc_points.pointCount):
        points.append(arc_points.getPart(i))
    return points


def _get_fp_geo(floodplain_file):
    """
    :param floodplain_file: shapefile of floodplain to measure
    :return: returns arcpy polygon geometry, throws error if floodplain has multiple features.
    """
    with arcpy.da.SearchCursor(floodplain_file, ['SHAPE@']) as cursor:
        rows = [row[0] for row in cursor]
        if len(rows) > 1:
            msg = 'Multiple features in the floodplain file: ' + str(floodplain_file) + \
                  ' Only using the first feature!!!'
            warn(msg)
        return rows[0]


def _get_xs_geo(xs_file, xs_id_field):
    """
    :param xs_file: shapefile of cross sections
    :param xs_id_field: field name of XS ids
    :return: returns sorted list of arcpy multiline geometry objects
    """
    cross_sections = []
    with arcpy.da.SearchCursor(xs_file, ['SHAPE@', xs_id_field]) as xs_cursor:
        for xs in xs_cursor:
            geo = xs[0]
            xs_id = float(xs[1])
            if geo.isMultipart:
                warn('Warning: Cross section ' + str(xs_id) + ' is multipart')
            new_xs = CrossSection(geo, xs_id)
            cross_sections.append(new_xs)
    cross_sections.sort(key=lambda x: x.xs_id)
    return cross_sections


def _setup_output_shapefile(filename, xs_id_field, spatial_reference):
    try:
        message('Creating output shapefile: ' + filename)
        arcpy.CreateFeatureclass_management(os.path.dirname(filename), os.path.basename(filename),
                                            'POLYLINE', '', '', '', spatial_reference)
        message('Adding fields...')
        arcpy.AddField_management(filename, xs_id_field, 'FLOAT', '')
        arcpy.AddField_management(filename, ERR_FIELD, 'TEXT', field_length=FIELD_LENGTH)
    except:
        error('Unable to create ' + filename +
              '. Is the shape file open in another program or is the workspace being edited?')
        sys.exit()
    else:
        arcpy.AddMessage('Done.')


class CrossSection(object):
    def __init__(self, geo, xs_id):
        # XS geometry in arcpy array format
        self.geo = geo
        self.xs_id = xs_id

        # XS geometry in list of arcpy points
        self.points = _array_to_list(self.geo.getPart(0))

        # Intersect points, starts as None until populated
        self.intersect_pts = None
        self.combo_points = None

        # This is likely unnecessary. The first point of self.points is probably ok. Just being safe.
        self.first_point = self.geo.firstPoint
        self.last_point = self.geo.lastPoint

        # top width line geo in list of arcpy points
        self.tw_points = None

        self.error_flag = False

    def __str__(self):
        return 'ID: ' + str(self.xs_id) + ' First point: ' + str(self.first_point) + ' WKT: ' + str(self.geo.WKT)

    def merge_points(self):
        """
        Merges the cross section vertices and points from intersection of cross section and floodplain
        into one list of sorted TWPoint objects
        """
        assert self.intersect_pts is not None

        self.combo_points = []

        # Start with xs_points
        for point in self.points:
            # line below should be updated to use measureONLine() THIS needs 10.2
            dist = self.geo.measureOnLine(point)
            # dist = _distance(self.first_point, point)
            next_point = TWPoint(point, XS_FLAG, dist)
            self.combo_points.append(next_point)

        # Do intersection points
        for point in self.intersect_pts:
            # line below should be updated to use measureONLine()
            dist = self.geo.measureOnLine(point)
            # dist = _distance(self.first_point, point)
            next_point = TWPoint(point, INTERSECT_FLAG, dist)
            self.combo_points.append(next_point)

        self.combo_points.sort(key=lambda x: x.dist)

    def extract_tw(self, fp_geo):
        """
        Creates a list of all points between the outer most TWPoints that are flagged with INTERSECT_FLAG

        :param fp_geo: arcpy geometry of floodplain
        :return: Nothing
        """
        left_intersect = None
        right_intersect = None

        # Check if cross section terminates inside floodplain
        if self.first_point.within(fp_geo):
            left_intersect = 0
        if self.last_point.within(fp_geo):
            right_intersect = len(self.combo_points)-1

        # Find index of left most intersect point
        if left_intersect is None:
            for i, point in enumerate(self.combo_points):
                if point.point_type == INTERSECT_FLAG:
                    left_intersect = i
                    break

        # Find index of right most intersect point (search backwards)
        if right_intersect is None:
            for i, point in reversed(list(enumerate(self.combo_points))):
                if point.point_type == INTERSECT_FLAG:
                    right_intersect = i
                    break

        # See if we got two points and bail if we didn't
        if left_intersect is None or right_intersect is None or left_intersect == right_intersect:
            return

        # Create the top width line
        new_points = []
        for i in range(left_intersect, right_intersect + 1):
            new_points.append(self.combo_points[i])
        self.tw_points = _tw_points_to_list(new_points)


class TWPoint(object):
    """ Holds point for sorting distance from start of line
    geo - arcpy point geo
    type - 'intersect' or 'cross section'
            defines whether the point is originally from the cross section or an intersection
            of the cross section and floodplain
    dist - distance to start of line
    """

    def __init__(self, geo, point_type, dist):
        self.geo = geo
        self.point_type = point_type
        self.dist = dist

    def __str__(self):
        return 'Geo: ' + str(self.geo) + ' Type: ' + str(self.point_type) + ' Dist: ' + str(self.dist)

    def __repr__(self):
        return self.__str__()
