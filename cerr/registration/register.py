import os
import tempfile
import shutil
from cerr.utils import uid
from cerr.dataclasses import deform as cerrDeform
from cerr.dataclasses import scan as scn
from cerr.dataclasses import structure as cerrStr
import cerr.plan_container as pc
from cerr.contour import rasterseg as rs
from cerr.utils.mask import getSurfacePoints
from cerr.utils.interp import finterp3
import numpy as np

def register_scans(basePlanC, baseScanIndex, movPlanC, movScanIndex, transformSaveDir):

    # create temporary directory to hold registration files
    dirpath = tempfile.mkdtemp()

    # Write nii files for base and moving scans in dirpath
    moving_img_nii = os.path.join(dirpath, 'ctmoving.nii.gz')
    fixed_img_nii = os.path.join(dirpath, 'ctfixed.nii.gz')
    basePlanC.scan[baseScanIndex].save_nii(fixed_img_nii)
    movPlanC.scan[movScanIndex].save_nii(moving_img_nii)

    plmCmdFile = 'plastimatch_ct_ct_intra_pt.txt'
    regDir = os.path.dirname(os.path.abspath(__file__))
    cmdFilePathSrc = os.path.join(regDir,'settings',plmCmdFile)
    #cmdFilePathDest = os.path.join(dirpath, plmCmdFile)
    #shutil.copyfile(cmdFilePathSrc, cmdFilePathDest)

    # Filename to save bsplines coeffficients
    bspSourcePath = os.path.join(dirpath, 'bspline_coefficients.txt')
    bspDestPath = os.path.join(transformSaveDir, 'bspline_coefficients.txt')

    plm_reg_cmd = "plastimatch register " + cmdFilePathSrc

    currDir = os.getcwd()
    os.chdir(dirpath)
    os.system(plm_reg_cmd)
    os.chdir(currDir)

    # Copy output to the user-specified directory
    shutil.copyfile(bspSourcePath, bspDestPath)

    # Create a deform object and add to planC
    deform = cerrDeform.Deform()
    deform.deformUID = uid.createUID("deform")
    deform.baseScanUID = basePlanC.scan[baseScanIndex].scanUID
    deform.movScanUID = movPlanC.scan[movScanIndex].scanUID
    deform.deformOutFileType = "plm_bspline_coeffs"
    deform.deformOutFilePath = bspDestPath
    deform.registrationTool = 'plastimatch'
    deform.algorithm = 'bsplines'

    # Append to base planc
    basePlanC.deform.append(deform)

    # Remove temporary directory
    shutil.rmtree(dirpath)

    return basePlanC


def warp_scan(basePlanC, baseScanIndex, movPlanC, movScanIndex, deformS):
    dirpath = tempfile.mkdtemp()
    fixed_img_nii = os.path.join(dirpath, 'ref.nii.gz')
    moving_img_nii = os.path.join(dirpath, 'ctmoving.nii.gz')
    warped_img_nii = os.path.join(dirpath, 'warped.nii.gz')
    bsplines_coeff_file = deformS.deformOutFilePath
    basePlanC.scan[baseScanIndex].save_nii(fixed_img_nii)
    movPlanC.scan[movScanIndex].save_nii(moving_img_nii)


    plm_warp_str_cmd = "plastimatch warp --input " + moving_img_nii + \
                  " --output-img " + warped_img_nii + \
                  " --xf " + bsplines_coeff_file + \
                  " --referenced-ct " + fixed_img_nii

    currDir = os.getcwd()
    os.chdir(dirpath)
    os.system(plm_warp_str_cmd)
    os.chdir(currDir)

    imageType = movPlanC.scan[movScanIndex].scanInfo[0].imageType
    basePlanC = pc.load_nii_scan(warped_img_nii, imageType, basePlanC)

    # Remove temporary directory
    shutil.rmtree(dirpath)

    return basePlanC


def warp_dose():
    pass

def warp_structures(basePlanC, baseScanIndex, movPlanC, movStrNumV, deformS):
    # dirpath = tempfile.mkdtemp()
    # rtst_warped_path = os.path.join(dirpath, 'struct.nii.gz')
    dirpath = tempfile.mkdtemp()
    fixed_img_nii = os.path.join(dirpath, 'ref.nii.gz')
    moving_str_nii = os.path.join(dirpath, 'structure.nii.gz')
    warped_str_nii = os.path.join(dirpath, 'warped.nii.gz')
    bsplines_coeff_file = deformS.deformOutFilePath
    basePlanC.scan[baseScanIndex].save_nii(fixed_img_nii)
    currDir = os.getcwd()
    os.chdir(dirpath)
    for strNum in movStrNumV:
        #movScanNum = scn.getScanNumFromUID(movPlanC.structure[strNum].assocScanUID, movPlanC)
        structName = movPlanC.structure[strNum].structureName
        movPlanC.structure[strNum].save_nii(moving_str_nii, movPlanC)
        plm_warp_str_cmd = "plastimatch warp --input " + moving_str_nii + \
                      " --output-img " + warped_str_nii + \
                      " --xf " + bsplines_coeff_file + \
                      " --fixed " + fixed_img_nii + \
                      " --interpolation nn"
        os.system(plm_warp_str_cmd)
        basePlanC = pc.load_nii_structure(warped_str_nii, baseScanIndex, basePlanC, {1: structName})

    os.chdir(currDir)

    # Remove temporary directory
    print(dirpath)
    #shutil.rmtree(dirpath)

    return basePlanC

def calc_vector_field(deformS, planC, baseScanNum, transformSaveDir):

    # create temporary directory to hold registration files
    dirpath = tempfile.mkdtemp()

    # Write nii files for base and moving scans in dirpath
    vf_nii_src = os.path.join(dirpath, 'vf.nii.gz')
    vf_nii_dest = os.path.join(transformSaveDir, 'vf.nii.gz')

    # Get x,y,z coordinate of the 1st voxel
    xV, yV, zV = planC.scan[baseScanNum].getScanXYZVals()
    spacing = [10*(xV[1]-xV[0]), 10*(yV[0]-yV[1]), 10*(zV[1]-zV[0])]
    if scn.flipSliceOrderFlag(planC.scan[baseScanNum]):
        cerrImgPatPos = [xV[0], yV[0], zV[-1], 1]
    else:
        cerrImgPatPos = [xV[0], yV[0], zV[0], 1]
    dcmImgPos = np.matmul(planC.scan[baseScanNum].cerrToDcmTransM, cerrImgPatPos)[:3]

    bsplines_coeff_file = deformS.deformOutFilePath

    plm_warp_str_cmd = "plastimatch xf-convert --input " + bsplines_coeff_file + \
                  " --output " + vf_nii_src + \
                  " --output-type vf" + \
                  " --spacing \"" + str(spacing[0]) + ' ' + str(spacing[1]) + ' ' + str(spacing[2]) + "\""\
                  " -- origin \"" + str(dcmImgPos[0]) + ' ' + str(dcmImgPos[1]) + ' ' + str(dcmImgPos[2]) + "\""

    print("======== plm command =======")
    print(plm_warp_str_cmd)

    currDir = os.getcwd()
    os.chdir(dirpath)
    os.system(plm_warp_str_cmd)
    os.chdir(currDir)

    # Copy output to the user-specified directory
    shutil.copyfile(vf_nii_src, vf_nii_dest)

    # Create a deform object and add to planC
    deform = cerrDeform.Deform()
    deform.deformUID = uid.createUID("deform")
    deform.baseScanUID = deformS.baseScanUID
    deform.movScanUID = deformS.baseScanUID
    deform.deformOutFileType = "vf"
    deform.deformOutFilePath = vf_nii_dest
    deform.registrationTool = deformS.registrationTool
    deform.algorithm = deformS.algorithm

    # Append to base planc
    planC.deform.append(deform)

    # Remove temporary directory
    shutil.rmtree(dirpath)

    return planC

def get_dvf_vectors(deformS, structNum, planC, sampleRate=1):

    # Get surface points
    assocScanNum = scn.getScanNumFromUID(planC.structure[structNum].assocScanUID, planC)
    mask3M = rs.getStrMask(structNum, planC)
    xValsV, yValsV, zValsV = planC.scan[assocScanNum].getScanXYZVals()
    #surfPoints = getSurfacePoints(mask3M, sampleRate, 1)
    #xSurfV = xValsV[surfPoints[:, 1]]
    #ySurfV = yValsV[surfPoints[:, 0]]
    #zSurfV = zValsV[surfPoints[:, 2]]
    surfPolygons =  cerrStr.getContourPolygons(structNum, planC, rcsFlag=False)
    surfPoints = np.array(surfPolygons[0])
    for poly in surfPolygons[1:]:
        surfPoints = np.append(surfPoints, poly, axis=0)
    xSurfV = surfPoints[:, 0]
    ySurfV = surfPoints[:, 1]
    zSurfV = surfPoints[:, 2]

    # Get x,y,z deformations at the surface points
    xV, yV, zV = deformS.getDVFXYZVals()
    delta = 1e-8
    zV[0] = zV[0] - 1e-3
    zV[-1] = zV[-1] + 1e-3
    xFieldV = np.asarray([xV[0] - delta, xV[1] - xV[0], xV[-1] + delta])
    yFieldV = np.asarray([yV[0] + delta, yV[1] - yV[0], yV[-1] - delta])
    zFieldV = np.asarray(zV)
    xDeformM = deformS.dvfMatrix[:,:,:,0]
    yDeformM = deformS.dvfMatrix[:,:,:,1]
    zDeformM = deformS.dvfMatrix[:,:,:,2]
    xDeformV = finterp3(xSurfV,ySurfV,zSurfV,xDeformM,xFieldV,yFieldV,zFieldV)
    yDeformV = finterp3(xSurfV,ySurfV,zSurfV,yDeformM,xFieldV,yFieldV,zFieldV)
    zDeformV = finterp3(xSurfV,ySurfV,zSurfV,zDeformM,xFieldV,yFieldV,zFieldV)

    numPts = len(yDeformV)
    vectors = np.empty((numPts,2,3), dtype=np.float32)
    if cerrDeform.flipSliceOrderFlag(deformS):
        zDeformV = - zDeformV
    for i in range(numPts):
        vectors[i,0,:] = [-ySurfV[i], xSurfV[i], zSurfV[i]]
        vectors[i,1,:] = [-yDeformV[i], xDeformV[i], zDeformV[i]]
    return vectors
