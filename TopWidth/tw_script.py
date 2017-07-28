import twcheck
import arcpy
import sys

# update text updates
twcheck.message = arcpy.AddMessage
twcheck.warn = arcpy.AddWarning
twcheck.error = arcpy.AddError

fp_file = arcpy.GetParameterAsText(0)
xsec_file = arcpy.GetParameterAsText(1)
xs_id_field = arcpy.GetParameterAsText(2)
out_file = arcpy.GetParameterAsText(3)

# make sure we have the right version, MeasureOnLine() requires >= 10.2.1
info = arcpy.GetInstallInfo()
if info['Version'] < '10.2.1':
    arcpy.AddError('Top Width Check requires ArcMap >= 10.2.1, you are using ' + info['Version'] + \
                   ', aborting.')
    sys.exit()

twcheck.measure(fp_file, xsec_file, xs_id_field, out_file)
