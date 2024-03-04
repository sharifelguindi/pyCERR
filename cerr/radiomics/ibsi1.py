import numpy as np

from cerr.radiomics import first_order, gray_level_cooccurence, run_length,\
    size_zone, neighbor_gray_level_dependence, neighbor_gray_tone
from cerr.utils.bbox import compute_boundingbox
from cerr.radiomics import preprocess, textureUtils
import json

def getDirectionOffsets(direction):
    if direction == 1:
        offsetsM = np.asarray([[1, 0, 0],
                               [0, 1, 0],
                               [1, 1, 0],
                               [1, -1, 0],
                               [0, 0, 1],
                               [1, 0, 1],
                               [1, 1, 1],
                               [1, -1, 1],
                               [0, 1, 1],
                               [0, -1, 1],
                               [-1, -1, 1],
                               [-1, 0, 1],
                               [-1, 1, 1]
                                            ],
                              dtype=int)
    elif direction == 2:
        offsetsM = np.asarray([[1, 0, 0],
                               [0, 1, 0],
                               [1, 1, 0],
                               [1, -1, 0]
                                        ],
                              dtype=int)

    return offsetsM


def calcRadiomicsForImgType(volToEval, maskBoundingBox3M, gridS, paramS):

    featDict = {}

    # Get feature extraction settings
    firstOrderOffsetEnergy = np.double(paramS['settings']['firstOrder']['offsetForEnergy'])
    firstOrderEntropyBinWidth = None
    firstOrderEntropyBinNum = None
    textureBinNum = None
    textureBinWidth = None
    if 'binWidthEntropy' in paramS['settings']['firstOrder'] \
        and isinstance(paramS['settings']['firstOrder']['binWidthEntropy'], (int, float)):
        firstOrderEntropyBinWidth = paramS['settings']['firstOrder']['binWidthEntropy']
    if 'binNumEntropy' in paramS['settings']['firstOrder'] \
        and isinstance(paramS['settings']['firstOrder']['binNumEntropy'], (int, float)):
        firstOrderEntropyBinNum = paramS['settings']['firstOrder']['binNumEntropy']
    if 'texture' in paramS['settings'] and paramS['settings']['texture'] != {}:
        if 'gtdm' in paramS['featureClass'] :
            patch_radius = paramS['settings']['texture']['patchRadiusVox']
        if'gldm' in paramS['featureClass'] :
            patch_radius = paramS['settings']['texture']['patchRadiusVox']
            difference_threshold = paramS['settings']['texture']['imgDiffThresh']
        if 'binwidth' in paramS['settings']['texture'] \
            and isinstance(paramS['settings']['texture']['binwidth'], (int, float)):
            textureBinWidth = paramS['settings']['texture']['binwidth']
        if 'binNum' in paramS['settings']['texture'] \
            and isinstance(paramS['settings']['texture']['binNum'], (int, float)):
            textureBinNum = paramS['settings']['texture']['binNum']
        if (textureBinNum is not None) and (textureBinWidth is not None):
            raise Exception("Please specify either the number of bins or bin-width for quantization")
        if any(name in ['glcm','glrlm','glszm'] for name in paramS['featureClass'].keys()):
            dirString = paramS['settings']['texture']['directionality']
            avgType = paramS['settings']['texture']['avgType']
            glcmVoxelOffset = paramS['settings']['texture']['voxelOffset']
            if avgType == 'feature':
                cooccurType = 2
                rlmType = 2
            elif avgType == 'texture':
                cooccurType = 1
                rlmType = 1
            if dirString == '3D':
                direction = 1
                szmDir = 1
            elif dirString == '2D':
                direction = 2
                szmDir = 2

        # Min/Max for image quantization
        minClipIntensity = None
        maxClipIntensity = None
        if 'minClipIntensity' in paramS['settings']['texture'] and \
               isinstance(paramS['settings']['texture']['minClipIntensity'], (int, float)):
            minClipIntensity = paramS['settings']['texture']['minClipIntensity']
        if 'maxClipIntensity' in paramS['settings']['texture'] and \
                isinstance(paramS['settings']['texture']['maxClipIntensity'], (int, float)):
            maxClipIntensity = paramS['settings']['texture']['maxClipIntensity']

    # Shape  features
    if 'shape' in paramS['featureClass'] and paramS['featureClass']['shape']["featureList"] != {}:
        from cerr.radiomics.shape import compute_shape_features
        featDict['shape'] = compute_shape_features(maskBoundingBox3M,gridS['xValsV'],gridS['yValsV'],gridS['zValsV'])

    # Assign nan values outside the mask, so that min/max within the mask are used for quantization
    volToEval[~maskBoundingBox3M] = np.nan

    # Texture-based scalar features
    if 'texture' in paramS['settings']:
        # Quantization
        quantized3M = preprocess.imquantize_cerr(volToEval, num_level=textureBinNum,\
                                                 xmin=minClipIntensity, xmax=maxClipIntensity, binwidth=textureBinWidth)
        nL = quantized3M.max()

        if any(name in ['glcm','glrlm','glszm'] for name in paramS['featureClass'].keys()):
            offsetsM = getDirectionOffsets(direction)
            offsetsM = offsetsM * glcmVoxelOffset
    else:
        quantized3M = volToEval

     # First order features
    if 'firstOrder' in paramS['featureClass'] and paramS['featureClass']['firstOrder']["featureList"] != {}:
        voxelVol = np.prod(gridS["PixelSpacingV"]) * 1000 # units of mm
        scanV = volToEval[maskBoundingBox3M]
        featDict['firstOrder'] = first_order.radiomics_first_order_stats(scanV, voxelVol,
                                        firstOrderOffsetEnergy, firstOrderEntropyBinWidth, firstOrderEntropyBinNum)

    # GLCM
    if 'glcm' in paramS['featureClass'] and paramS['featureClass']['glcm']["featureList"] != {}:
        glcmM = gray_level_cooccurence.calcCooccur(quantized3M, offsetsM, nL, cooccurType)
        featDict['glcm'] = gray_level_cooccurence.cooccurToScalarFeatures(glcmM)

    # RLM
    if 'glrlm' in paramS['featureClass'] and paramS['featureClass']['glrlm']["featureList"] != {}:
        rlmM = run_length.calcRLM(quantized3M,offsetsM,nL,rlmType)
        numVoxels = np.sum(maskBoundingBox3M.astype(int))
        featDict['glrlm'] = run_length.rlmToScalarFeatures(rlmM, numVoxels)

    # SZM
    if 'glszm' in paramS['featureClass'] and paramS['featureClass']['glszm']["featureList"] != {}:
        szmM = size_zone.calcSZM(quantized3M,nL,szmDir)
        numVoxels = np.sum(maskBoundingBox3M.astype(int))
        featDict['glszm'] = size_zone.szmToScalarFeatures(szmM, numVoxels)

    # NGLDM
    if 'gldm' in paramS['featureClass'] and paramS['featureClass']['gldm']["featureList"] != {}:
        s = neighbor_gray_level_dependence.calcNGLDM(quantized3M, patch_radius, nL, difference_threshold)
        featDict['gldm'] = neighbor_gray_level_dependence.ngldmToScalarFeatures(s, numVoxels)

    # NGTDM
    if 'gtdm' in paramS['featureClass'] and paramS['featureClass']['gtdm']["featureList"] != {}:
        s,p = neighbor_gray_tone.calcNGTDM(quantized3M, patch_radius, nL)
        featDict['gtdm'] = neighbor_gray_tone.ngtdmToScalarFeatures(s,p,numVoxels)

    return featDict



def computeScalarFeatures(scanNum, structNum, settingsFile, planC):

    with open(settingsFile, ) as settingsFid:
        radiomicsSettingS = json.load(settingsFid)

    # Pre-process Image
    (processedScan3M, processedMask3M, gridS, radiomicsSettingS, diagS) = \
       preprocess.preProcessForRadiomics(scanNum, structNum, radiomicsSettingS, planC)
    minr,maxr,minc,maxc,mins,maxs,__ = compute_boundingbox(processedMask3M)
    voxSizeV = gridS["PixelSpacingV"]

    ############################################
    # Calculate IBSI-1 features
    ############################################
    imgTypeDict = radiomicsSettingS['imageType']
    imgTypes = imgTypeDict.keys()
    featDictAllTypes = {}

    # Loop over image filters
    for imgType in imgTypes:
        if imgType.lower() == "original":
            # Calc. radiomic features
            maskBoundingBox3M = processedMask3M[minr:maxr+1, minc:maxc+1, mins:maxs+1]
            croppedScan3M = processedScan3M[minr:maxr+1, minc:maxc+1, mins:maxs+1]
            featDict = calcRadiomicsForImgType(croppedScan3M, maskBoundingBox3M, gridS, radiomicsSettingS)
        else:
            # Extract filter & padding parameters
            filterParamS = radiomicsSettingS['imageType'][imgType]
            padSizeV = [0,0,0]
            padMethod = "none"
            if 'padding' in radiomicsSettingS["settings"] and radiomicsSettingS["settings"]["padding"]["method"].lower()!='none':
                padSizeV = radiomicsSettingS["settings"]["padding"]["size"]
                padMethod = radiomicsSettingS["settings"]["padding"]["method"]
            filterParamS["VoxelSize_mm"]  = voxSizeV * 10
            filterParamS["Padding"] = {"Size":padSizeV,"Method": padMethod,"Flag":False}

            # Apply image filter
            paddedResponseS = textureUtils.processImage(imgType, processedScan3M, processedMask3M, filterParamS)
            filterName = list(paddedResponseS.keys())[0] # must be single output
            filteredPadScan3M = paddedResponseS[filterName]

            # Remove padding
            maskBoundingBox3M = processedMask3M[minr:maxr+1, minc:maxc+1, mins:maxs+1]
            filteredScan3M = filteredPadScan3M[minr:maxr+1, minc:maxc+1, mins:maxs+1]
            filteredScan3M[~maskBoundingBox3M] = np.nan
            # Calc. radiomic features
            featDict = calcRadiomicsForImgType(filteredScan3M, maskBoundingBox3M, gridS, radiomicsSettingS)

        # Aggregate features
        #imgType = imgType + equivalent of createFieldNameFromParameters
        avgType = ''
        directionality = ''
        if 'texture' in radiomicsSettingS['settings']:
            avgType = radiomicsSettingS['settings']['texture']['avgType']
            directionality = radiomicsSettingS['settings']['texture']['directionality']

        mapToIBSI = False
        if 'mapFeaturenamesToIBSI' in radiomicsSettingS['settings'] and \
                radiomicsSettingS['settings']['mapFeaturenamesToIBSI'] == "yes":
            mapToIBSI = True
        featDictAllTypes = {**featDictAllTypes, **createFlatFeatureDict(featDict, imgType, avgType, directionality, mapToIBSI)}

    return featDictAllTypes, diagS

def getIBSINameMap():
    classDict = {'shape': 'morph',
                 'firstOrder': 'stat',
                 'glcm': 'cm',
                 'glrlm': 'rlm',
                 'glszm': 'szm',
                 'gldm': 'ngl',
                 'gtdm': 'ngt'}
    featDict = {'majorAxis': 'pca_maj_axis',
                'minorAxis':'pca_min_axis',
                'leastAxis': 'pca_least_axis',
                'flatness': 'pca_flatness',
                'elongation': 'pca_elongation',
                'max3dDiameter': 'diam',
                'max2dDiameterAxialPlane': 'max2dDiameterAxialPlane',
                'max2dDiameterSagittalPlane': 'max2dDiameterSagittalPlane',
                'max2dDiameterCoronalPlane': 'max2dDiameterCoronalPlane',
                'surfArea': 'area_mesh',
                'volume': 'vol_approx',
                'filledVolume': 'filled_vol_approx',
                'Compactness1': 'comp_1',
                'Compactness2': 'comp_2',
                'spherDisprop': 'sph_dispr',
                'sphericity': 'sphericity',
                'surfToVolRatio': 'av',
                'min': 'min',
                'max': 'max',
                'mean': 'mean',
                'range': 'range',
                'std': 'std',
                'var': 'var',
                'median': 'median',
                'skewness': 'skew',
                'kurtosis': 'kurt',
                'entropy': 'entropy',
                'rms': 'rms',
                'energy': 'energy',
                'totalEnergy': 'total_energy',
                'meanAbsDev': 'mad',
                'medianAbsDev': 'medad',
                'P10': 'p10',
                'P90': 'p90',
                'robustMeanAbsDev': 'maad',
                'robustMedianAbsDev': 'medaad',
                'interQuartileRange': 'iqr',
                'coeffDispersion': 'qcod',
                'coeffVariation': 'cov',
                'energy': 'energy',
                'jointEntropy': 'joint_entr',
                'jointMax': 'joint_max',
                'jointAvg': 'joint_avg',
                'jointVar': 'joint_var',
                'sumAvg': 'sum_avg',
                'sumVar': 'sum_var',
                'sumEntropy': 'sum_entr',
                'contrast': 'contrast',
                'invDiffMom': 'inv_diff_mom',
                'invDiffMomNorm': 'inv_diff_mom_norm',
                'invDiff': 'inv_diff',
                'invDiffNorm': 'inv_diff_norm',
                'invVar': 'inv_var',
                'dissimilarity': 'dissimilarity',
                'diffEntropy': 'diff_entr',
                'diffVar': 'diff_var',
                'diffAvg': 'diff_avg',
                'sumAvg': 'sum_avg',
                'sumVar': 'sum_var',
                'sumEntropy': 'sum_entr',
                'corr': 'corr',
                'clustTendency': 'clust_tend',
                'clustShade': 'clust_shade',
                'clustPromin': 'clust_prom',
                'haralickCorr': 'haral_corr',
                'autoCorr': 'auto_corr',
                'firstInfCorr': 'info_corr1',
                'secondInfCorr': 'info_corr2',
                'shortRunEmphasis': 'sre',
                'longRunEmphasis': 'lre',
                'grayLevelNonUniformity': 'glnu',
                'grayLevelNonUniformityNorm': 'glnu_norm',
                'runLengthNonUniformity': 'rlnu',
                'runLengthNonUniformityNorm': 'rlnu_norm',
                'runPercentage': 'r_perc',
                'lowGrayLevelRunEmphasis': 'lgre',
                'highGrayLevelRunEmphasis': 'hgre',
                'shortRunLowGrayLevelEmphasis': 'srlge',
                'shortRunHighGrayLevelEmphasis': 'srhge',
                'longRunLowGrayLevelEmphasis': 'lrlge',
                'longRunHighGrayLevelEmphasis': 'lrhge',
                'grayLevelVariance': 'gl_var',
                'runLengthVariance': 'rl_var',
                'runEntropy': 'rl_entr',
                'smallAreaEmphasis': 'sze',
                'largeAreaEmphasis': 'lze',
                'sizeZoneNonUniformity': 'sznu',
                'sizeZoneNonUniformityNorm': 'sznu_norm',
                'zonePercentage': 'z_perc',
                'lowGrayLevelZoneEmphasis': 'lgze',
                'highGrayLevelZoneEmphasis': 'hzge',
                'smallAreaLowGrayLevelEmphasis': 'szlge',
                'largeAreaHighGrayLevelEmphasis': 'lzhge',
                'smallAreaHighGrayLevelEmphasis': 'szhge',
                'largeAreaLowGrayLevelEmphasis': 'lzlge',
                'sizeZoneVariance': 'zs_var',
                'zoneEntropy': 'zs_entr',
                'LowDependenceEmphasis': 'lde',
                'HighDependenceEmphasis': 'hde',
                'LowGrayLevelCountEmphasis': 'lgce',
                'HighGrayLevelCountEmphasis': 'hgce',
                'LowDependenceLowGrayLevelEmphasis': 'ldlge',
                'LowDependenceHighGrayLevelEmphasis': 'ldhge',
                'HighDependenceLowGrayLevelEmphasis': 'hdlge',
                'HighDependenceHighGrayLevelEmphasis': 'hdhge',
                'DependenceCountNonuniformity': 'dcnu',
                'DependenceCountNonuniformityNorm': 'dcnu_norm',
                'DependenceCountPercentage': 'dc_perc',
                'DependenceCountVariance': 'dc_var',
                'DependenceCountEntropy': 'dc_entr',
                'DependenceCountEnergy': 'dc_energy',
                'coarseness': 'coarseness',
                'busyness': 'busyness',
                'complexity': 'complexity',
                'strength': 'strength',
                }

    return classDict, featDict


def createFlatFeatureDict(featDict, imageType, avgType, directionality, mapToIBSI = False):
    featClasses = featDict.keys()
    flatFeatDict = {}
    if avgType == 'feature':
        avgString = 'avg'
    else:
        avgString = 'comb'
    if directionality.lower() == '2d':
        dirString = '2_5D'
    else:
        dirString = '3D'
    if mapToIBSI:
        classDict, featDict = getIBSINameMap()
    for featClass in featClasses:
        if mapToIBSI:
            featClass = classDict[featClass]
        for item in featDict[featClass].items():
            itemName = item[0]
            if mapToIBSI:
                itemName = featDict[itemName]
            if featClass in ["glcm", "glrlm"]:
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + \
                             '_' + dirString + '_' + avgString] = np.mean(item[1])
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + \
                             '_' + dirString + '_Median'] = np.median(item[1])
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + \
                             '_' + dirString + '_StdDev'] = np.std(item[1], ddof=1)
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + \
                             '_' + dirString + '_Min'] = np.min(item[1])
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + \
                              '_' + dirString + '_Max'] = np.max(item[1])
            else:
                flatFeatDict[imageType + '_' + featClass + '_' + itemName + '_' + dirString] = item[1]
    return flatFeatDict

def writeFeaturesToFile(featList, csvFileName, writeHeader = True):
    import csv
    if not isinstance(featList,list):
        featList = [featList]
    with open(csvFileName, 'a', newline='') as csvfile:
        flatFeatDict = featList[0]
        fieldnames = flatFeatDict.keys()
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if writeHeader:
            writer.writeheader()
        for flatFeatDict in featList:
            writer.writerow(flatFeatDict)
