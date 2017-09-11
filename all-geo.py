"""
all-geo.py v0.01

Runs tools for n-value, iefa, and obstruction review. Applies appropriate style
and adds layers to current mxd. This must be run from arcgis.

Mike Bannister
mike.bannister@respec.com
2017
"""

# TODO - All Tools: search for missing reaches in GIS vs RAS

import arcpy
import sys
import os
path = os.path.join(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(path, 'Block Obs Review'))
sys.path.insert(0, os.path.join(path, 'IEFA Review'))
sys.path.insert(0, os.path.join(path, 'N-value Review'))
import blocked_review
import iefa_review
import n_value_review

OVER_WRITE = True
IEFA_STYLE = r".\layer_styles\iefa_style.lyr"
OBSTRUCTION_STYLE = r".\layer_styles\obstruction_style.lyr"
N_VALUE_STYLE = r".\layer_styles\n_value_style.lyr"

def file_check(outfile):
    """
    Checks if outfile exists and deletes it if OVER_WRITE is true
    """
    if os.path.isfile(outfile):
        if OVER_WRITE:
            arcpy.AddWarning(outfile + ' exists. Deleting.')
            arcpy.Delete_management(outfile)
        else:
            arcpy.AddError(outfile + ' exists and over write is turned off!')
            raise Exception(outfile + ' exists and overwirte is turned off')

def main():
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df = mxd.activeDataFrame
        
    # Get parameters from Arc
    geofile = arcpy.GetParameterAsText(0)
    xs_shape_file = arcpy.GetParameterAsText(1)
    xs_id_field = arcpy.GetParameterAsText(2)
    river_field = arcpy.GetParameterAsText(3)
    reach_field = arcpy.GetParameterAsText(4)
    out_dir = arcpy.GetParameterAsText(5)
    out_prefix = arcpy.GetParameterAsText(6)

    # Grab model name from RAS geometry file or use supplied name for shapefiles
    if out_prefix == '':
        geo_name = geofile.split('\\')[-1][:-4]
    else:
        geo_name = out_prefix

    if not os.path.exists(out_dir):
        os.mkdir(out_dir)
   
    arcpy.AddMessage('\n'+'*'*20+' Creating N-value review lines... ')
    outfile = os.path.join(out_dir, geo_name + '_n_value.shp')
    file_check(outfile)
    n_value_review.n_value_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile)
    new_layer = arcpy.mapping.Layer(outfile)
    arcpy.ApplySymbologyFromLayer_management(new_layer, N_VALUE_STYLE)

    # Set labels
    new_layer.showLabels = True
    for label_class in new_layer.labelClasses:
        label_class.expression = '"<ITA><FNT size=\'11\'>"&[Mannings_n]&"</FNT></ITA>"'
    arcpy.mapping.AddLayer(df, new_layer, "AUTO_ARRANGE")
    
    arcpy.AddMessage('\n'+'*'*20+' Creating IEFA review lines... ')
    outfile = os.path.join(out_dir, geo_name + '_iefa.shp')
    file_check(outfile)
    iefa_review.iefa_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile)
    new_layer = arcpy.mapping.Layer(outfile)
    arcpy.ApplySymbologyFromLayer_management(new_layer, IEFA_STYLE)
    arcpy.mapping.AddLayer(df, new_layer, "AUTO_ARRANGE")
    
    arcpy.AddMessage('\n'+'*'*20+' Creating obstruction review lines... ')
    outfile = os.path.join(out_dir, geo_name + '_blocked.shp')
    file_check(outfile)
    blocked_review.obstruction_review(geofile, xs_shape_file, xs_id_field, river_field, reach_field, outfile)
    new_layer = arcpy.mapping.Layer(outfile)
    arcpy.ApplySymbologyFromLayer_management(new_layer, OBSTRUCTION_STYLE)
    arcpy.mapping.AddLayer(df, new_layer, "AUTO_ARRANGE")

    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

if __name__ == '__main__':
    main()
