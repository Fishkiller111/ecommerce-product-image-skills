#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <CoreImage/CoreImage.h>
#import <ImageIO/ImageIO.h>
int main(int argc, const char * argv[]) { @autoreleasepool {
if (argc != 3) { fprintf(stderr,"usage: mask input output\n"); return 1; }
NSURL *src=[NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]]; NSURL *dst=[NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[2]]];
CGImageSourceRef source=CGImageSourceCreateWithURL((__bridge CFURLRef)src,NULL); if(!source)return 2;
CGImageRef img=CGImageSourceCreateImageAtIndex(source,0,NULL); if(!img)return 3;
VNGenerateForegroundInstanceMaskRequest *req=[VNGenerateForegroundInstanceMaskRequest new]; req.usesCPUOnly=YES;
VNImageRequestHandler *handler=[[VNImageRequestHandler alloc] initWithCGImage:img options:@{}]; NSError *err=nil;
if(![handler performRequests:@[req] error:&err]) { NSLog(@"%@",err); return 4; }
VNInstanceMaskObservation *obs=req.results.firstObject;
if(!obs || obs.allInstances.count == 0) { fprintf(stderr,"no instance found\n"); return 5; }
CVPixelBufferRef mask=[obs generateScaledMaskForImageForInstances:obs.allInstances fromRequestHandler:handler error:&err];
if(!mask) { NSLog(@"%@",err); return 6; }
CIImage *orig=[[CIImage alloc] initWithCGImage:img]; CIImage *m=[[CIImage alloc] initWithCVPixelBuffer:mask];
CIFilter *filter=[CIFilter filterWithName:@"CIBlendWithMask"];
[filter setValue:orig forKey:kCIInputImageKey]; [filter setValue:[[CIImage imageWithColor:[CIColor colorWithRed:0 green:0 blue:0 alpha:0]] imageByCroppingToRect:orig.extent] forKey:kCIInputBackgroundImageKey]; [filter setValue:m forKey:kCIInputMaskImageKey];
CGColorSpaceRef space=CGColorSpaceCreateWithName(kCGColorSpaceSRGB); CIContext *ctx=[CIContext contextWithOptions:nil];
BOOL ok=[ctx writePNGRepresentationOfImage:filter.outputImage toURL:dst format:kCIFormatRGBA8 colorSpace:space options:@{} error:&err];
if (!ok) { NSLog(@"%@",err); return 7; }
printf("instances=%lu width=%zu height=%zu\n",(unsigned long)obs.allInstances.count,CGImageGetWidth(img),CGImageGetHeight(img)); CFRelease(mask); CGColorSpaceRelease(space); CGImageRelease(img); CFRelease(source); return 0;
} }
